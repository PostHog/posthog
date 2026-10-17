"""Facade for native delivery: how other products plug in destinations and their own wording."""

from __future__ import annotations

from typing import TYPE_CHECKING

from products.alerts_platform.backend.delivery import addresses, describers, destinations, legacy_webhook
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    DestinationResolver,
    LegacyWebhookBody,
    SourceDescriber,
    SourceKind,
)

if TYPE_CHECKING:
    from posthog.models import Team


def register_destination_resolver(resolver: DestinationResolver) -> None:
    destinations.register(resolver)


def register_source_describer(source: SourceKind, describer: SourceDescriber) -> None:
    describers.register(source, describer)


def refused_destination(data: AlertDestinationData) -> str | None:
    """Why native delivery would refuse to send to this destination, or None when it would send."""
    return addresses.refused_destination(data)


def register_legacy_webhook_body(source: SourceKind, body: LegacyWebhookBody) -> None:
    legacy_webhook.register(source, body)


def keeps_legacy_webhook_body(team: Team) -> bool | None:
    """Whether native delivery sends this team the legacy webhook body. None when the flag could not be read."""
    return legacy_webhook.keeps_legacy_webhook_body(team)
