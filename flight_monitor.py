import asyncio
import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from playwright.async_api import async_playwright

DEPARTURE = "PAS"
ARRIVAL = "ATH"
DATE = "2026-07-25"
TARGET_TIME = "11:35"
EMAIL_TO = "jtseng1999@gmail.com"
STATE_FILE = Path(".flight_monitor_state.json")
GOOGLE_FLIGHTS_URL = f"https://www.google.com/travel/flights/search?flt={DEPARTURE}.{ARRIVAL}.{DATE}"

async def check_availability():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US"
        )
        page = await context.new_page()

        # Mask automation signals
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            print(f"Navigating to Google Flights: {GOOGLE_FLIGHTS_URL}")
            await page.goto(GOOGLE_FLIGHTS_URL, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(5000)

            # Save screenshot for debugging (visible in GitHub Actions artifacts)
            await page.screenshot(path="flight_check.png")

            content = await page.content()

            # Check for our target flight time
            if TARGET_TIME not in content:
                print(f"Flight at {TARGET_TIME} not found on page.")
                await browser.close()
                return {"available": None, "url": GOOGLE_FLIGHTS_URL}

            # If the time IS on the page, check for "Sold out" nearby
            sold_out_indicators = ["Sold out", "sold out", "SOLD OUT"]
            is_sold_out = any(indicator in content for indicator in sold_out_indicators)

            print(f"Flight {TARGET_TIME} found. Sold out: {is_sold_out}")
            await browser.close()
            return {"available": not is_sold_out, "url": GOOGLE_FLIGHTS_URL}

        except Exception as e:
            print(f"Error during page check: {e}")
            await browser.close()
            return {"available": None, "url": GOOGLE_FLIGHTS_URL}

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"was_available": False, "last_check": None}

def save_state(is_available):
    STATE_FILE.write_text(json.dumps({
        "was_available": is_available,
        "last_check": datetime.utcnow().isoformat()
    }))

def send_email(result):
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not password:
        print("GMAIL_APP_PASSWORD not set — skipping email.")
        return

    is_available = result.get("available")
    url = result.get("url", GOOGLE_FLIGHTS_URL)

    if is_available:
        subject = f"🎉 SEATS AVAILABLE: {DEPARTURE}→{ARRIVAL} on July 25"
        body = f"""SEATS FOUND! Book immediately!

Flight Details:
• Route: {DEPARTURE} (Paros) → {ARRIVAL} (Athens)
• Date: July 25, 2026
• Departure: {TARGET_TIME}
• Status: ✅ SEATS AVAILABLE

Book here: {url}

— Flight Monitor
"""
    else:
        subject = f"Flight Check: {DEPARTURE}→{ARRIVAL} on July 25"
        body = f"""Flight Status Update:

• Route: {DEPARTURE} (Paros) → {ARRIVAL} (Athens)
• Date: July 25, 2026
• Departure: {TARGET_TIME}
• Status: ❌ Still Sold Out

Search link: {url}

— Flight Monitor
"""

    msg = MIMEMultipart()
    msg["From"] = EMAIL_TO
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_TO, password)
            server.send_message(msg)
        print("Email sent!")
    except Exception as e:
        print(f"Email failed: {e}")

async def main():
    print(f"[{datetime.utcnow().isoformat()}] Checking {DEPARTURE}→{ARRIVAL} on {DATE}")

    result = await check_availability()
    is_available = result.get("available")

    if is_available is None:
        print("Could not determine availability — skipping state update.")
        sys.exit(0)

    state = load_state()
    print(f"Previous: {'available' if state['was_available'] else 'sold out'} | Current: {'available' if is_available else 'sold out'}")

    if is_available and not state["was_available"]:
        print("Status changed to AVAILABLE — sending alert!")
        send_email(result)
    elif not is_available and state["was_available"]:
        print("Status changed to SOLD OUT — notifying of change.")
        send_email(result)

    save_state(is_available)
    sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
