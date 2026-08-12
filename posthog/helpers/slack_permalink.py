import re
from urllib.parse import parse_qs, urlparse


def parse_slack_thread_url(url: str) -> tuple[str, str] | None:
    """Parse a Slack permalink into `(channel, thread_ts)`"""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    match = re.search(r"/archives/(?P<channel>[A-Z0-9]+)/p(?P<ts>\d+)", parsed.path)
    if not match:
        return None
    channel = match.group("channel")
    # Reply permalinks put the parent thread_ts in the query string; that wins over the in-path ts.
    thread_ts_from_query = parse_qs(parsed.query).get("thread_ts", [None])[0]
    if thread_ts_from_query:
        return channel, thread_ts_from_query
    raw_ts = match.group("ts")
    if len(raw_ts) < 7:
        return None
    return channel, f"{raw_ts[:-6]}.{raw_ts[-6:]}"
