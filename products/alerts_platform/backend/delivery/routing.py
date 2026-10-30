"""Sends an evaluation's messages to the team-wide receivers whose routes match the alert.

Runs in its own activity, after the alert's own destinations have had their sends, so a receiver
that fails retries on its own and can never cost those destinations their message.
"""

from dataclasses import replace
from typing import Final

import structlog

from posthog.models import Team
from posthog.utils import absolute_uri

from products.alerts_platform.backend.delivery.dispatch import deliver
from products.alerts_platform.backend.delivery.evaluation import _TRANSPORTS
from products.alerts_platform.backend.delivery.team_flags import team_flag_enabled
from products.alerts_platform.backend.delivery.thread_store import DatabaseThreadStore, ThreadBusy
from products.alerts_platform.backend.delivery.transport import DeliveryError, DeliveryTransport
from products.alerts_platform.backend.facade.contracts import AlertDeliveryRequest, EvaluationAnnouncement, MessageLink
from products.alerts_platform.backend.logic import delivery_holds
from products.alerts_platform.backend.logic.alert_destinations import INCIDENT_DESTINATION_TYPES
from products.alerts_platform.backend.logic.alert_routes import RoutedReceiver, routed_receivers
from products.alerts_platform.backend.logic.platform_alert_events import announcement
from products.alerts_platform.backend.models import PlatformAlertConfiguration

logger = structlog.get_logger(__name__)

ROUTING_FLAG: Final = "platform-alerts-routing"


def routing_is_enabled(team: Team) -> bool:
    """Fail closed, so a flag-eval blip sends to the alert's own destinations only."""
    try:
        return bool(team_flag_enabled(ROUTING_FLAG, team))
    except Exception:
        logger.warning("alerts_platform_routing_flag_check_failed_defaulting_off", team_id=team.id, exc_info=True)
        return False


def _message_transport(receiver: RoutedReceiver) -> type[DeliveryTransport] | None:
    destination_type = receiver.data.get("type")
    if not destination_type or destination_type in INCIDENT_DESTINATION_TYPES:
        return None
    return _TRANSPORTS.get(destination_type)


def _routing_team(request: AlertDeliveryRequest) -> Team | None:
    if not request.owned_by_platform or not request.sends_messages:
        return None
    team = Team.objects.filter(id=request.team_id).first()
    if team is None or not routing_is_enabled(team):
        return None
    if delivery_holds.blocks_delivery(request.team_id, request.configuration_id, request.evaluation_key):
        return None
    return team


def deliver_routes(request: AlertDeliveryRequest) -> int:
    """How many receivers were sent to. Messages only: an incident manager needs its trigger and
    resolve paired, which the source decides from the alert's own destinations.

    Raises like a delivery does, so the activity retries: `ThreadBusy` for a held thread, else
    `DeliveryError`. A receiver already sent to is skipped on the retry by its thread claim.
    """
    team = _routing_team(request)
    if team is None:
        return 0
    labels = (
        PlatformAlertConfiguration.objects.for_team(request.team_id)
        .filter(id=request.configuration_id)
        .values_list("labels", flat=True)
        .first()
    )
    receivers = routed_receivers(team_id=request.team_id, labels=labels or {})
    if not receivers:
        return 0
    announced = announcement(
        request.team_id,
        request.configuration_id,
        request.evaluation_key,
        source=request.source,
        incident_grouping_keys=request.incident_actions.keys(),
        part=request.part,
        parts=request.parts,
    )
    if announced is None:
        return 0
    return _deliver_to(receivers, request=request, team=team, announced=announced)


def _deliver_to(
    receivers: tuple[RoutedReceiver, ...],
    *,
    request: AlertDeliveryRequest,
    team: Team,
    announced: EvaluationAnnouncement,
) -> int:
    thread_store = DatabaseThreadStore(request.team_id)
    project = MessageLink(label=team.name, url=absolute_uri(f"/project/{team.id}"))
    sent = 0
    busy: list[str] = []
    failures: list[str] = []
    for receiver in receivers:
        transport_class = _message_transport(receiver)
        transitions = tuple(
            transition
            for transition in announced.transitions
            if transition.kind.value in request.event_ids_by_kind and transition.kind in receiver.event_kinds
        )
        if transport_class is None or not transitions:
            continue
        try:
            deliver(
                transport=transport_class(),
                thread_store=thread_store,
                team_id=request.team_id,
                configuration_id=request.configuration_id,
                evaluation_key=request.evaluation_key,
                target=receiver.data,
                destination_id=str(receiver.id),
                announcement=replace(announced, transitions=transitions, overflowed=0),
                source_alert_url=request.source_alert_url,
                project=project,
            )
        except ThreadBusy as error:
            busy.append(str(error))
        except DeliveryError as error:
            failures.append(str(error))
        except Exception as error:
            # Named by class only, because an exception's text can carry a credential URL.
            failures.append(type(error).__name__)
        else:
            sent += 1
    # A held thread wins over a failure, as in `deliver_evaluation`: the workflow waits it out and
    # reruns every receiver, which retries the failed ones too.
    if busy:
        raise ThreadBusy("; ".join([*busy, *failures]))
    if failures:
        raise DeliveryError(f"{len(failures)} receiver(s) failed: " + "; ".join(failures))
    return sent
