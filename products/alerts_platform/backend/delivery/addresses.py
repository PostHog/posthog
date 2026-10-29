"""Whether native delivery would send to a stored destination, without loading the delivery runtime."""

from __future__ import annotations

from typing import Final

from products.alerts_platform.backend.delivery.discord import DiscordTransport
from products.alerts_platform.backend.delivery.teams import TeamsTransport
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.delivery.webhook import WebhookTransport
from products.alerts_platform.backend.delivery.webhook_url import WebhookUrlTransport
from products.alerts_platform.backend.facade.contracts import (
    DEFAULT_PAGERDUTY_REGION,
    DEFAULT_PAGERDUTY_SEVERITY,
    AlertDestinationData,
    DestinationType,
    PagerDutyRegion,
    PagerDutySeverity,
)

_URL_TRANSPORTS: Final[dict[DestinationType, type[WebhookUrlTransport]]] = {
    DestinationType.WEBHOOK: WebhookTransport,
    DestinationType.TEAMS: TeamsTransport,
    DestinationType.DISCORD: DiscordTransport,
}


def refused_destination(data: AlertDestinationData) -> str | None:
    """Why native delivery would refuse to send to this destination, or None when it would send."""
    if data["type"] == DestinationType.PAGERDUTY:
        # The HogFunction template maps an unknown value to a default. Native delivery refuses it.
        try:
            PagerDutyRegion(data.get("pagerduty_region") or DEFAULT_PAGERDUTY_REGION)
            PagerDutySeverity(data.get("pagerduty_severity") or DEFAULT_PAGERDUTY_SEVERITY)
        except ValueError:
            return "This PagerDuty destination has an unknown region or severity."
        return None
    transport = _URL_TRANSPORTS.get(data["type"])
    url = data.get("webhook_url")
    if transport is None:
        return None
    if not isinstance(url, str):
        return "This destination needs a web address."
    try:
        transport().check_url(url)
    except DeliveryError as error:
        return str(error)
    return None
