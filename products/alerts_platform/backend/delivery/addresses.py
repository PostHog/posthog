"""Whether native delivery would send to a stored address, without loading the delivery runtime."""

from __future__ import annotations

from typing import Final

from products.alerts_platform.backend.delivery.discord import DiscordTransport
from products.alerts_platform.backend.delivery.teams import TeamsTransport
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.delivery.webhook import WebhookTransport
from products.alerts_platform.backend.delivery.webhook_url import WebhookUrlTransport
from products.alerts_platform.backend.facade.contracts import DestinationType

_URL_TRANSPORTS: Final[dict[DestinationType, type[WebhookUrlTransport]]] = {
    DestinationType.WEBHOOK: WebhookTransport,
    DestinationType.TEAMS: TeamsTransport,
    DestinationType.DISCORD: DiscordTransport,
}


def refused_address(destination_type: DestinationType, url: str) -> str | None:
    """Why native delivery would refuse to send to this URL, or None when it would send."""
    transport = _URL_TRANSPORTS.get(destination_type)
    if transport is None:
        return None
    try:
        transport().check_url(url)
    except DeliveryError as error:
        return str(error)
    return None
