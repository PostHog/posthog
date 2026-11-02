"""Read a Slack message link back into the channel and message it points at.

Slack's "Copy link" gives `https://<workspace>.slack.com/archives/<channel>/p<ts>`, with the ts's
dot dropped: ten digits of seconds, then six of microseconds. Copied from a reply, the link also
carries `?thread_ts=<root ts>&cid=<channel>`, which names the thread the reply is in.
"""

import re
from urllib.parse import parse_qs, urlparse

from posthog.dataclasses import frozen

_ARCHIVES_PATH_RE = re.compile(r"^/archives/([A-Z0-9]+)/p(\d{10})(\d{6})/?$")
_TS_RE = re.compile(r"^\d{10}\.\d{6}$")


@frozen
class SlackMessageLink:
    channel_id: str
    # The message the link points at, in Slack's own "1700000000.000100" form.
    message_ts: str
    # The root of the thread the message is a reply in, when the link says so. A link copied from
    # a thread's root (or from any reply, in some clients) leaves it out, and only Slack can tell.
    thread_ts: str | None


def parse_message_link(url: str) -> SlackMessageLink | None:
    """The channel and message a Slack message link points at, or None for any other URL."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "slack.com" or host.endswith(".slack.com")):
        return None
    match = _ARCHIVES_PATH_RE.match(parsed.path)
    if match is None:
        return None
    channel_id, seconds, micros = match.groups()
    thread_ts = next(iter(parse_qs(parsed.query).get("thread_ts", [])), None)
    return SlackMessageLink(
        channel_id=channel_id,
        message_ts=f"{seconds}.{micros}",
        thread_ts=thread_ts if thread_ts and _TS_RE.match(thread_ts) else None,
    )
