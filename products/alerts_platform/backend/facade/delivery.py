"""Facade for native delivery: how other products plug in destinations and their own wording."""

from __future__ import annotations

from typing import TYPE_CHECKING

from products.alerts_platform.backend.delivery import (
    addresses,
    delivery_paths,
    describers,
    destinations,
    legacy_webhook,
    transition_events,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    DeliveryPathChooser,
    DestinationResolver,
    LegacyEventEmitter,
    LegacyWebhookBody,
    SourceDescriber,
    SourceFacts,
    SourceKind,
    TransitionEventProducer,
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


def register_delivery_path_chooser(chooser: DeliveryPathChooser) -> None:
    """The product that owns destinations decides, per alert, whether native delivery may send them."""
    delivery_paths.register_chooser(chooser)


def register_legacy_event_emitter(source: SourceKind, emitter: LegacyEventEmitter) -> None:
    """A source's alerts on the HogFunction path send through the internal events this emits."""
    delivery_paths.register_emitter(source, emitter)


def native_sends_legacy_webhook_body(source: SourceKind, team: Team) -> bool | None:
    """Whether a stock webhook receives the body its HogFunction sent when delivered natively. None when unknown."""
    return legacy_webhook.native_sends_legacy_body(source, team)


def register_transition_event_producer(producer: TransitionEventProducer) -> None:
    """The product that produces internal events puts the platform's `$alert_transition` events on the topic."""
    transition_events.register_producer(producer)


def register_source_facts(source: SourceKind, facts: SourceFacts) -> None:
    """A source's facts ride on each `$alert_transition` under the property names its own alert events used."""
    transition_events.register_source_facts(source, facts)
