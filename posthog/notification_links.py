"""Channel tagging for links we send people outside the app.

An arrival in the app carries no usable trace of the link that produced it: Slack's desktop app
and most link hops report no referrer, so referrer sniffing cannot separate Slack from GitHub
from a pasted link. Tagging the link where it is built is what makes the channel readable.
"""

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

NOTIFICATION_UTM_MEDIUM = "notification"
NOTIFICATION_UTM_CAMPAIGN = "self-driving-report"

# Query parameter carrying the id of the send that produced a link, joining an arrival back to
# its `signals_notification_sent` / `pr_notification_sent` event.
NOTIFICATION_ID_PARAM = "nid"


def tag_notification_url(url: str, *, source: str, surface: str, notification_id: str | None = None) -> str:
    """Add campaign parameters naming the channel and surface that carried this link.

    `utm_*` rather than private parameter names: posthog-js already captures campaign parameters,
    so the channel reaches analytics with no client-side change, and `utm_medium=notification` is
    the one key that keeps these internal links out of marketing acquisition reporting.

    `source` is where the person was when they clicked (`slack`, `github`), `surface` is which
    card or body held the link. Pass `notification_id` when the link belongs to a single send, so
    click-through can be measured per send; omit it for a link embedded once and read many times,
    such as the report link in a PR description.

    Existing query parameters on `url` are preserved.
    """
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params.update(
        {
            "utm_source": source,
            "utm_medium": NOTIFICATION_UTM_MEDIUM,
            "utm_campaign": NOTIFICATION_UTM_CAMPAIGN,
            "utm_content": surface,
        }
    )
    if notification_id:
        params[NOTIFICATION_ID_PARAM] = notification_id
    return urlunparse(parsed._replace(query=urlencode(params)))
