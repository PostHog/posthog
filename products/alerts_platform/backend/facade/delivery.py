"""Facade for native delivery: how other products plug in destinations and their own wording."""

from products.alerts_platform.backend.delivery import describers, destinations, legacy_webhook
from products.alerts_platform.backend.facade.contracts import (
    DestinationResolver,
    LegacyWebhookBody,
    SourceDescriber,
    SourceKind,
)


def register_destination_resolver(resolver: DestinationResolver) -> None:
    destinations.register(resolver)


def register_source_describer(source: SourceKind, describer: SourceDescriber) -> None:
    describers.register(source, describer)


def register_legacy_webhook_body(source: SourceKind, body: LegacyWebhookBody) -> None:
    legacy_webhook.register(source, body)
