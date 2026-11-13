"""Sends an evaluation's messages and incident events to the team-wide receivers whose routes match the alert.

Runs in its own activity, after the alert's own destinations have had their sends, so a receiver
that fails retries on its own and can never cost those destinations their message.
"""

from dataclasses import replace

import structlog

from posthog.models import Team
from posthog.utils import absolute_uri

from products.alerts_platform.backend.delivery.dispatch import deliver
from products.alerts_platform.backend.delivery.evaluation import _TRANSPORTS, announcement_to_deliver
from products.alerts_platform.backend.delivery.thread_store import DatabaseThreadStore, ThreadBusy
from products.alerts_platform.backend.delivery.transport import (
    DeliveryError,
    DestinationMisconfigured,
    RefusedEverywhere,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AnnouncedTransition,
    EvaluationAnnouncement,
    IncidentAction,
    MessageLink,
)
from products.alerts_platform.backend.logic import delivery_holds
from products.alerts_platform.backend.logic.alert_destinations import INCIDENT_DESTINATION_TYPES
from products.alerts_platform.backend.logic.alert_routes import (
    RoutedReceiver,
    has_incident_receiver,
    routed_receivers,
    routing_is_enabled,
)
from products.alerts_platform.backend.logic.platform_reads import rule_metadata

logger = structlog.get_logger(__name__)


def _routing_team(request: AlertDeliveryRequest) -> Team | None:
    if not request.owned_by_platform:
        return None
    # A delivery that exists only for its incident actions has nothing for a chat receiver.
    if not request.sends_messages and not has_incident_receiver(request.team_id):
        return None
    team = Team.objects.filter(id=request.team_id).first()
    if team is None or not routing_is_enabled(team):
        return None
    if delivery_holds.blocks_delivery(request.team_id, request.configuration_id, request.evaluation_key):
        return None
    return team


def deliver_routes(request: AlertDeliveryRequest) -> int:
    """How many receivers were sent to. A chat receiver hears the transitions its routes asked for,
    and an incident manager hears every trigger and resolve, whatever kinds its routes list: one that
    heard a trigger and not its resolve would keep the incident open.

    Raises like a delivery does, so the activity retries: `ThreadBusy` for a held thread, else
    `DeliveryError`. A receiver already sent to is skipped on the retry by its thread claim.
    """
    team = _routing_team(request)
    if team is None:
        return 0
    rule = rule_metadata(request.team_id, request.configuration_id)
    receivers = routed_receivers(team_id=request.team_id, labels=rule.labels)
    # A delivery that exists only for its incident actions has nothing for a chat receiver.
    if not request.sends_messages:
        receivers = tuple(r for r in receivers if r.data.get("type") in INCIDENT_DESTINATION_TYPES)
    if not receivers:
        return 0
    announced = announcement_to_deliver(request, path="routed")
    if announced is None:
        return 0
    pages = any(receiver.data.get("type") in INCIDENT_DESTINATION_TYPES for receiver in receivers)
    if pages and (stale := delivery_holds.stale_held_triggers(request, announced.transitions)):
        request = replace(
            request,
            incident_actions={key: action for key, action in request.incident_actions.items() if key not in stale},
        )
    return _deliver_to(receivers, request=request, team=team, announced=replace(announced, rule=rule))


def _sends(
    receiver: RoutedReceiver, request: AlertDeliveryRequest, announced: EvaluationAnnouncement
) -> list[tuple[tuple[AnnouncedTransition, ...], IncidentAction | None]]:
    """What one receiver is sent, as the transitions of each send and the incident action they carry."""
    if receiver.data.get("type") in INCIDENT_DESTINATION_TYPES:
        return [
            (
                tuple(t for t in announced.transitions if request.incident_actions.get(t.grouping_key) == action),
                action,
            )
            for action in IncidentAction
            if action.value in request.event_ids_by_incident_action
        ]
    transitions = tuple(
        transition
        for transition in announced.transitions
        if transition.kind.value in request.event_ids_by_kind and transition.kind in receiver.event_kinds
    )
    return [(transitions, None)]


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
    retryable = False
    for receiver in receivers:
        transport_class = _TRANSPORTS.get(receiver.data.get("type"))
        sends = [(transitions, action) for transitions, action in _sends(receiver, request, announced) if transitions]
        if transport_class is None or not sends:
            continue
        try:
            for transitions, action in sends:
                deliver(
                    transport=transport_class(),
                    thread_store=thread_store,
                    team_id=request.team_id,
                    configuration_id=request.configuration_id,
                    evaluation_key=request.evaluation_key,
                    target=receiver.data,
                    destination_id=str(receiver.id),
                    announcement=replace(announced, transitions=transitions, overflowed=0),
                    incident_action=action,
                    source_alert_url=request.source_alert_url,
                    project=project,
                )
        except ThreadBusy as error:
            busy.append(str(error))
        except DeliveryError as error:
            failures.append(str(error))
            retryable = retryable or not isinstance(error, DestinationMisconfigured)
        except Exception as error:
            # Named by class only, because an exception's text can carry a credential URL.
            failures.append(type(error).__name__)
            retryable = True
        else:
            sent += 1
    # A held thread wins over a failure, as in `deliver_evaluation`: the workflow waits it out and
    # reruns every receiver, which retries the failed ones too.
    if busy:
        raise ThreadBusy("; ".join([*busy, *failures]))
    if failures:
        failed = DeliveryError if retryable else RefusedEverywhere
        raise failed(f"{len(failures)} receiver(s) failed: " + "; ".join(failures))
    return sent
