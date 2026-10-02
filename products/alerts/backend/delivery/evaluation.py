"""One evaluation, from the address a delivery carries to the messages it sends.

The layer that knows a transport exists. `dispatch.deliver` handles one destination, and this
is what decides which destinations there are and which transport each one takes.
"""

from typing import Final

import structlog

from posthog.dataclasses import frozen

from products.alerts.backend.delivery.dispatch import deliver
from products.alerts.backend.delivery.slack import SlackTransport
from products.alerts.backend.delivery.thread_store import DatabaseThreadStore
from products.alerts.backend.delivery.transport import DeliveryTransport
from products.alerts.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertDestinationData,
    DestinationType,
    EvaluationAnnouncement,
)
from products.alerts.backend.facade.destinations import list_alert_destination_groups
from products.alerts.backend.logic.platform_alert_events import announcement

logger = structlog.get_logger(__name__)

# Whether a destination the platform resolves is one the platform is allowed to contact. A
# constant until the flag exists, at which point this and the legacy path both read it, so a
# team is served by one deliverer rather than both.
DESTINATIONS_ARE_LIVE: Final = False

# A destination type with no entry here has no native transport. An alert that uses one is not
# eligible for native delivery at all, which is checked before a team is made live rather than
# branched on per destination: one alert delivering natively to Slack and through a HogFunction
# to Discord would send two differently worded messages for one event.
_TRANSPORTS: Final[dict[DestinationType, type[DeliveryTransport]]] = {DestinationType.SLACK: SlackTransport}


@frozen
class DeliveryOutcome:
    """What one evaluation's delivery did, for the activity to log and count."""

    sent: int
    skipped_without_transport: int


def deliver_evaluation(request: AlertDeliveryRequest) -> DeliveryOutcome:
    """Sends what one evaluation decided, to every destination configured for it."""
    announced = announcement(request.team_id, request.configuration_id, request.evaluation_key)
    if announced is None:
        return DeliveryOutcome(sent=0, skipped_without_transport=0)

    thread_store = DatabaseThreadStore(request.team_id)
    sent = 0
    skipped = 0
    for target in _destinations(request, announced):
        transport_class = _TRANSPORTS.get(target["type"])
        if transport_class is None:
            skipped += 1
            continue
        deliver(
            transport=transport_class(),
            thread_store=thread_store,
            team_id=request.team_id,
            configuration_id=request.configuration_id,
            evaluation_key=request.evaluation_key,
            target=target,
            announcement=announced,
        )
        sent += 1
    return DeliveryOutcome(sent=sent, skipped_without_transport=skipped)


def _destinations(request: AlertDeliveryRequest, announced: EvaluationAnnouncement) -> list[AlertDestinationData]:
    """Where this evaluation goes, resolved now rather than pinned when the check ran.

    A destination removed between the check and the send is not sent to, which a pinned set
    would get wrong. The event ids come from the kinds this evaluation actually announced, so a
    destination configured for firings only does not receive a resolve.
    """
    event_ids = {
        request.event_ids_by_kind[transition.kind.value]
        for transition in announced.transitions
        if transition.kind.value in request.event_ids_by_kind
    }
    if not event_ids:
        return []
    groups = list_alert_destination_groups(
        team_id=request.team_id,
        alert_id=request.destination_alert_id,
        allowed_event_ids=sorted(event_ids),
    )
    return [group.data for group in groups if group.fully_enabled]
