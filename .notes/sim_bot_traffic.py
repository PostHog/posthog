#!/usr/bin/env python3
"""
Simulate bot traffic for testing the live dashboard bot panels.

Sends $pageview events with known bot user agents to the PostHog capture API.
Events flow through Kafka → livestream service (bot classification) → SSE → browser.

Usage:
    python .notes/sim_bot_traffic.py                    # 60 events over 2 minutes
    python .notes/sim_bot_traffic.py --count 200        # 200 events
    python .notes/sim_bot_traffic.py --burst             # all at once
    python .notes/sim_bot_traffic.py --host us.posthog.com  # prod
"""

import argparse
import random
import time
import uuid

import requests

# 🧪 Test project
DEFAULT_API_KEY = "phc_B4gdR6FVgobcyd4PMiPNtrmLpmVFcytEwJUKBrcWtc4T"
DEFAULT_HOST = "http://localhost:8000"

BOT_USER_AGENTS = [
    # AI crawlers
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)",
    "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)",
    "Mozilla/5.0 (compatible; Google-Extended; +http://google.com)",
    "CCBot/2.0 (https://commoncrawl.org/faq/)",
    # AI search
    "Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
    # Search crawlers
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
    # SEO crawlers
    "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)",
    "Mozilla/5.0 (compatible; SemrushBot/7~bl; +http://www.semrush.com/bot.html)",
    # HTTP clients
    "curl/8.5.0",
    "python-requests/2.31.0",
    # Headless browsers
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/120.0.6099.216 Safari/537.36",
    # Monitoring
    "Mozilla/5.0 (compatible; UptimeRobot/2.0; http://www.uptimerobot.com/)",
]

PAGES = [
    "/", "/pricing", "/docs", "/blog", "/about", "/careers",
    "/product/analytics", "/product/session-replay", "/product/feature-flags",
    "/docs/api", "/docs/libraries/python", "/docs/libraries/js",
    "/blog/best-open-source-analytics", "/blog/posthog-vs-amplitude",
    "/customers", "/contact", "/signup", "/login",
]


def send_batch(host: str, api_key: str, events: list[dict]) -> None:
    for event in events:
        payload = {"api_key": api_key, **event}
        # Try multiple endpoints — local dev routes differ from prod
        for path in ["/capture/", "/batch/", "/e/"]:
            resp = requests.post(
                f"{host}{path}",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if resp.status_code == 200:
                return
        resp.raise_for_status()


def make_event(api_key: str) -> dict:
    ua = random.choice(BOT_USER_AGENTS)
    page = random.choice(PAGES)
    return {
        "event": "$pageview",
        "api_key": api_key,
        "distinct_id": f"bot-sim-{uuid.uuid4().hex[:8]}",
        "properties": {
            "$current_url": f"https://posthog.com{page}",
            "$pathname": page,
            "$host": "posthog.com",
            "$user_agent": ua,
            "$raw_user_agent": ua,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate bot traffic for live dashboard testing")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--burst", action="store_true", help="Send all events at once")
    args = parser.parse_args()

    events = [make_event(args.api_key) for _ in range(args.count)]

    if args.burst:
        # Send in batches of 50
        for i in range(0, len(events), 50):
            batch = events[i : i + 50]
            send_batch(args.host, args.api_key, batch)
            print(f"Sent batch {i // 50 + 1} ({len(batch)} events)")
    else:
        delay = 120.0 / args.count  # spread over 2 minutes
        for i, event in enumerate(events):
            send_batch(args.host, args.api_key, [event])
            ua_short = event["properties"]["$user_agent"].split("/")[0].split("(")[-1].split(";")[0].strip()
            print(f"[{i + 1}/{args.count}] {ua_short} → {event['properties']['$pathname']}")
            if i < len(events) - 1:
                time.sleep(delay)

    print(f"\nDone — sent {args.count} bot events to {args.host}")


if __name__ == "__main__":
    main()
