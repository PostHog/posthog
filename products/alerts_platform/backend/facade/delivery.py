"""Facade for native delivery: how other products plug in destinations and their own wording."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from products.alerts_platform.backend.delivery import (
    addresses,
    delivery_paths,
    describers,
    destinations,
    legacy_webhook,
    recipients,
    refusal_notices,
    subscribers,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertDestinationData,
    DeliveryPathChooser,
    DeliveryTestOutcome,
    DestinationResolver,
    LateImageResult,
    LegacyEventEmitter,
    LegacyWebhookBody,
    LinkedHogFunctionRetirer,
    LiveHogFunctionLookup,
    SourceAlertCreator,
    SourceDescriber,
    SourceImageResolver,
    SourceKind,
    SourceRecipients,
    SourceSlackRenderer,
    SubscriberAccess,
)
from products.alerts_platform.backend.logic import alert_destinations

if TYPE_CHECKING:
    from posthog.models import Team


def register_destination_resolver(resolver: DestinationResolver) -> None:
    destinations.register(resolver)


def register_live_hog_function_lookup(lookup: LiveHogFunctionLookup) -> None:
    """The product that owns HogFunctions says which still exist, so a destination row that copies one waits for it to go."""
    destinations.register_live_hog_function_lookup(lookup)


def register_linked_hog_function_retirer(retirer: LinkedHogFunctionRetirer) -> None:
    """The product that owns HogFunctions retires the ones a deleted destination row links to."""
    alert_destinations.register_linked_hog_function_retirer(retirer)


def register_source_recipients(source: SourceKind, lookup: SourceRecipients) -> None:
    recipients.register(source, lookup)


def register_subscriber_access(source: SourceKind, access: SubscriberAccess) -> None:
    subscribers.register(source, access)


def register_source_alert_creator(source: SourceKind, lookup: SourceAlertCreator) -> None:
    refusal_notices.register_creator(source, lookup)


def register_source_describer(source: SourceKind, describer: SourceDescriber) -> None:
    describers.register(source, describer)


def register_image_resolver(source: SourceKind, resolver: SourceImageResolver) -> None:
    describers.register_image_resolver(source, resolver)


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


def has_legacy_event_emitter(source: SourceKind) -> bool:
    """Whether the source emits its own events for the HogFunction path. Without an emitter, an alert
    on that path would deliver natively, so its customized destinations would lose what they add."""
    return delivery_paths.emitter_for(source) is not None


def has_legacy_webhook_body(source: SourceKind) -> bool:
    """Whether native delivery can send the source's legacy webhook body to the teams that keep it."""
    return legacy_webhook.body_for(source) is not None


def register_source_slack_renderer(source: SourceKind, renderer: SourceSlackRenderer) -> None:
    describers.register_slack_renderer(source, renderer)


def add_late_image(request: AlertDeliveryRequest, late_detail: dict[str, Any]) -> LateImageResult:
    """Puts the image the source draws from `late_detail` into the Slack messages the evaluation's
    firings opened, once they have gone out without it. `late_detail` is what the check would have
    recorded in `source_detail` had it been ready."""
    # Imported here, so the modules that import this facade as they load do not pull in every transport.
    from products.alerts_platform.backend.delivery.evaluation import (  # noqa: PLC0415
        add_late_image as add_late_image_to_evaluation,
    )

    return add_late_image_to_evaluation(request, late_detail)


def delivery_test_destination_ids(*, team_id: int, public_id: UUID) -> frozenset[UUID]:
    """The alert's destination rows that `send_delivery_test` sends to: enabled ones that hear firings, on
    an alert the platform sends, other than subscribers, incident managers, and rows a live HogFunction
    stands behind. A source sends its own test to its subscribers and its HogFunctions."""
    return frozenset(
        destination.id
        for destination in alert_destinations.delivery_test_destinations(team_id=team_id, public_id=public_id)
    )


def send_delivery_test(
    *, team_id: int, public_id: UUID, source: SourceKind, alert_name: str, source_alert_url: str
) -> DeliveryTestOutcome:
    """Sends one test message, worded as a firing of `alert_name`, to each destination
    `delivery_test_destination_ids` names, through native delivery. A destination that fails does not
    stop the others, and is counted in `failed`."""
    # Imported here, so the modules that import this facade as they load do not pull in every transport.
    from products.alerts_platform.backend.delivery.trial_send import send_delivery_test as send  # noqa: PLC0415

    return send(
        team_id=team_id, public_id=public_id, source=source, alert_name=alert_name, source_alert_url=source_alert_url
    )
