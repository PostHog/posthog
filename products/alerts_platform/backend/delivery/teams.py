"""Microsoft Teams delivery, as an Adaptive Card posted to a Teams workflow URL.

The card is version 1.2, the same envelope the HogFunction template posts, so every URL shape
that template accepts takes this one too.
"""

import re
import json
from typing import Any, Final

from posthog.security.url_validation import is_microsoft_teams_webhook_url

from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.delivery.webhook_url import WebhookUrlTransport

PROVIDER: Final = "teams"

# Teams rejects a payload over about 28 KB, so the card's text stays under this as sent and leaves
# room for the JSON envelope. Counting characters instead would let emoji or non-Latin text past.
TEXT_BUDGET_BYTES: Final = 20_000

# The alert name and a query error are user-written, and a TextBlock or a fact renders markdown.
# Escaping links, emphasis and code stops `[x](https://...)` hiding where it goes, and a bare URL
# shows itself. Each extra character is one more stray backslash if a client shows them literally.
_MARKDOWN_SPECIALS: Final = re.compile(r"([\\`*_\[\]])")


def escape_markdown(text: str) -> str:
    return _MARKDOWN_SPECIALS.sub(r"\\\1", text)


def _wire_size(text: str) -> int:
    # The bytes this string costs in the request body. JSON doubles every backslash the markdown
    # escaping added, so the text's own UTF-8 length undercounts.
    return len(json.dumps(text, ensure_ascii=False).encode())


def _clip(text: str, budget: int) -> str:
    if _wire_size(text) <= budget:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if _wire_size(text[:middle] + "…") <= budget:
            low = middle
        else:
            high = middle - 1
    return text[:low] + "…"


def card_for(message: AlertMessage) -> dict[str, Any]:
    headline = escape_markdown(message.headline)
    body: list[dict[str, Any]] = [{"type": "TextBlock", "text": headline, "weight": "Bolder", "wrap": True}]
    if message.details:
        # An error message can carry a whole query, so it is a detail that overflows. Each detail
        # gets an equal share, so clipping the error cannot drop the failure count after it.
        share = (TEXT_BUDGET_BYTES - _wire_size(headline)) // len(message.details)
        body.append(
            {
                "type": "FactSet",
                "facts": [
                    {"title": detail.label, "value": _clip(escape_markdown(detail.value), share)}
                    for detail in message.details
                ],
            }
        )
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.2",
                    "body": body,
                },
            }
        ],
    }


class TeamsTransport(WebhookUrlTransport):
    provider = PROVIDER
    display_name = "Microsoft Teams"

    def check_url(self, url: str) -> None:
        if not is_microsoft_teams_webhook_url(url):
            raise DeliveryError("This Microsoft Teams destination's URL is not a Teams workflow URL.")

    def body_for(self, message: AlertMessage) -> dict[str, Any]:
        return card_for(message)
