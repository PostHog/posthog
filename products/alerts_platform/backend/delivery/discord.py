"""Discord delivery, as a plain markdown message posted to a channel webhook.

Plain content rather than an embed, because that is what the HogFunction template sends, so a
Discord channel sees the same kind of message from either path.
"""

import re
from typing import Any, Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from posthog.security.url_validation import has_authority_bypass_chars
from posthog.slack.channels import clip_text

from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.delivery.webhook_url import WebhookUrlTransport

PROVIDER: Final = "discord"

MAX_CONTENT_CHARS: Final = 2000

# Stops a URL in a query error from unfurling into a preview of a page the alert never chose.
SUPPRESS_EMBEDS: Final = 1 << 2

# Discord honors a backslash before any of these, so escaped text renders as typed. `#` and `-`
# are here because a query error can span lines, and either one starts a heading or a list.
_MARKDOWN_SPECIALS: Final = re.compile(r"([\\*_~`|\[\]<>#-])")


def escape_markdown(text: str) -> str:
    return _MARKDOWN_SPECIALS.sub(r"\\\1", text)


def content_for(message: AlertMessage) -> str:
    headline = f"**{escape_markdown(message.headline)}**"
    lines = [f"**{detail.label}:** {escape_markdown(detail.value)}" for detail in message.details]
    if not lines:
        return headline
    content = f"{headline}\n\n" + "\n".join(lines)
    if len(content) <= MAX_CONTENT_CHARS:
        return content
    # An error message can carry a whole query, so it is a detail that overflows. Each detail gets
    # an equal share, so clipping the error cannot drop the failure count after it.
    share = (MAX_CONTENT_CHARS - len(headline) - 2 - (len(lines) - 1)) // len(lines)
    return f"{headline}\n\n" + "\n".join(clip_text(line, share) for line in lines)


class DiscordTransport(WebhookUrlTransport):
    provider = PROVIDER
    display_name = "Discord"

    def check_url(self, url: str) -> None:
        # The URL shape the HogFunction template accepts, so no destination that works today is refused.
        refused = DeliveryError("This Discord destination's URL is not a Discord webhook URL.")
        if has_authority_bypass_chars(url):
            raise refused
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise refused from None
        if (
            parts.scheme != "https"
            or parts.hostname != "discord.com"
            or port not in (None, 443)
            or parts.username is not None
            or not parts.path.startswith("/api/webhooks/")
        ):
            raise refused

    def send_url(self, url: str) -> str:
        # Without `wait=true` Discord answers before it saves the message, and a message it then
        # fails to save returns no error, so the send would be recorded as delivered.
        parts = urlsplit(url)
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "wait"]
        return urlunsplit(parts._replace(query=urlencode([*query, ("wait", "true")])))

    def body_for(self, message: AlertMessage) -> dict[str, Any]:
        return {
            "content": content_for(message),
            # An alert name or a query error can contain `@everyone` or a role mention. Nobody is
            # pinged by an alert, which matches the template's default.
            "allowed_mentions": {"parse": []},
            "flags": SUPPRESS_EMBEDS,
        }
