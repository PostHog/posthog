"""One evaluation, from the address a delivery carries to the messages it sends.

The layer that knows a transport exists. `dispatch.deliver` handles one destination, and this
is what decides which destinations there are and which transport each one takes.
"""

from dataclasses import replace
from typing import Final

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts_platform.backend.delivery.destinations import list_alert_destination_groups
from products.alerts_platform.backend.delivery.dispatch import deliver
from products.alerts_platform.backend.delivery.slack import SlackTransport
from products.alerts_platform.backend.delivery.thread_store import DatabaseThreadStore, ThreadBusy
from products.alerts_platform.backend.delivery.transport import DeliveryTransport
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertDestinationData,
    AnnouncedTransition,
    DestinationType,
    EvaluationAnnouncement,
)
from products.alerts_platform.backend.logic.platform_alert_events import announcement

logger = structlog.get_logger(__name__)

# Whether the platform may contact a team's destinations. Only the platform reads it: the
# production logs path keeps delivering regardless, so a team with this on receives the legacy
# message and the native one. Flipping a team from one deliverer to the other is the cutover,
# and it is not this.
LIVE_DELIVERY_FLAG: Final = "alert-platform-live-delivery"

# A destination type with no entry here has no native transport, and delivery skips it. Make a
# team live only when its alerts use no such type. Nothing checks this in code, and one alert
# delivering natively to Slack and through a HogFunction to Discord would send two differently
# worded messages for one event.
_TRANSPORTS: Final[dict[DestinationType, type[DeliveryTransport]]] = {DestinationType.SLACK: SlackTransport}


@frozen
class DeliveryOutcome:
    """What one evaluation's delivery did, for the activity to log and count."""

    live: bool
    sent: int
    skipped_without_transport: int


def destinations_are_live(team: Team) -> bool:
    """Whether this team's destinations are the platform's to contact.

    Fail closed. A flag-eval blip leaves the production logs path as the only deliverer, which
    is where everything was before this existed. Reading a blip the other way starts sending.
    """
    try:
        return bool(
            posthoganalytics.feature_enabled(
                LIVE_DELIVERY_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                # This runs in a Temporal activity, where a captured event is silently dropped.
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.warning(
            "alerts_platform_live_delivery_flag_check_failed_defaulting_off",
            team_id=team.id,
            exc_info=True,
        )
        return False


def deliver_evaluation(request: AlertDeliveryRequest) -> DeliveryOutcome:
    """Sends what one evaluation decided, to every destination configured for it."""
    team = Team.objects.filter(id=request.team_id).first()
    if team is None or not destinations_are_live(team):
        return DeliveryOutcome(live=False, sent=0, skipped_without_transport=0)

    announced = announcement(request.team_id, request.configuration_id, request.evaluation_key)
    if announced is None:
        return DeliveryOutcome(live=True, sent=0, skipped_without_transport=0)

    thread_store = DatabaseThreadStore(request.team_id)
    sent = 0
    skipped = 0
    busy: list[str] = []
    # Per subscription rather than per destination. A destination subscribes to some of the
    # kinds an alert can announce, so one that asked for firings must not be handed the resolve
    # that another group produced in the same evaluation.
    for event_id, transitions in _by_subscription(request, announced).items():
        for target in _destinations(request, event_id):
            transport_class = _TRANSPORTS.get(target["type"])
            if transport_class is None:
                skipped += 1
                continue
            try:
                deliver(
                    transport=transport_class(),
                    thread_store=thread_store,
                    team_id=request.team_id,
                    configuration_id=request.configuration_id,
                    evaluation_key=request.evaluation_key,
                    target=target,
                    announcement=replace(announced, transitions=transitions),
                )
            except ThreadBusy as error:
                busy.append(str(error))
            else:
                sent += 1
    if busy:
        raise ThreadBusy("; ".join(busy))
    return DeliveryOutcome(live=True, sent=sent, skipped_without_transport=skipped)


def _by_subscription(
    request: AlertDeliveryRequest, announced: EvaluationAnnouncement
) -> dict[str, tuple[AnnouncedTransition, ...]]:
    """The transitions this evaluation announced, grouped by the event a destination subscribes to.

    A kind the source does not map to an event id reaches nobody: no destination can have asked
    for it.
    """
    grouped: dict[str, list[AnnouncedTransition]] = {}
    for transition in announced.transitions:
        event_id = request.event_ids_by_kind.get(transition.kind.value)
        if event_id is None:
            continue
        grouped.setdefault(event_id, []).append(transition)
    return {event_id: tuple(transitions) for event_id, transitions in grouped.items()}


def _destinations(request: AlertDeliveryRequest, event_id: str) -> list[AlertDestinationData]:
    """Who subscribed to this event, resolved now rather than pinned when the check ran.

    A destination removed between the check and the send is not sent to, which a pinned set
    would get wrong.
    """
    groups = list_alert_destination_groups(
        team_id=request.team_id,
        alert_id=request.destination_alert_id,
        allowed_event_ids=[event_id],
    )
    return [group.data for group in groups if group.fully_enabled]
