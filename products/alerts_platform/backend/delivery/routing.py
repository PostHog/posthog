"""Sends an evaluation's messages to the team-wide receivers whose routes match each group's labels.

Runs in its own activity, after the alert's own destinations have had their sends, so a receiver
that fails retries on its own and can never cost those destinations their message.
"""

from dataclasses import replace
from uuid import UUID

import structlog

from posthog.models import Team
from posthog.utils import absolute_uri

from products.alerts_platform.backend.delivery.dispatch import deliver
from products.alerts_platform.backend.delivery.evaluation import _TRANSPORTS, announcement_to_deliver
from products.alerts_platform.backend.delivery.team_flags import team_flag_enabled
from products.alerts_platform.backend.delivery.thread_store import DatabaseThreadStore, ThreadBusy
from products.alerts_platform.backend.delivery.transport import (
    DeliveryError,
    DeliveryTransport,
    DestinationMisconfigured,
    RefusedEverywhere,
)
from products.alerts_platform.backend.facade.contracts import (
    ROUTING_FLAG,
    AlertDeliveryRequest,
    AnnouncedTransition,
    EvaluationAnnouncement,
    MessageLink,
)
from products.alerts_platform.backend.logic import delivery_holds
from products.alerts_platform.backend.logic.alert_destinations import INCIDENT_DESTINATION_TYPES
from products.alerts_platform.backend.logic.alert_routes import (
    RoutedReceiver,
    has_enabled_routes,
    routed_receivers_for_label_sets,
    routing_labels,
)
from products.alerts_platform.backend.logic.platform_reads import rule_metadata

logger = structlog.get_logger(__name__)


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

    Each group is routed on its own labels with the rule's on top, so one evaluation can reach
    different receivers for different groups.

    Raises like a delivery does, so the activity retries: `ThreadBusy` for a held thread, else
    `DeliveryError`. A receiver already sent to is skipped on the retry by its thread claim.
    """
    team = _routing_team(request)
    if team is None or not has_enabled_routes(request.team_id):
        return 0
    announced = announcement_to_deliver(request, path="routed")
    if announced is None:
        return 0
    rule = rule_metadata(request.team_id, request.configuration_id)
    routed = _routed_transitions(request, rule_labels=rule.labels, transitions=announced.transitions)
    if not routed:
        return 0
    return _deliver_to(routed, request=request, team=team, announced=replace(announced, rule=rule))


def _routed_transitions(
    request: AlertDeliveryRequest,
    *,
    rule_labels: dict[str, str],
    transitions: tuple[AnnouncedTransition, ...],
) -> list[tuple[RoutedReceiver, tuple[AnnouncedTransition, ...]]]:
    """Each matched receiver with the transitions it hears, in route order of first match."""
    keys = [
        tuple(sorted(routing_labels(group_labels=transition.labels, rule_labels=rule_labels).items()))
        for transition in transitions
    ]
    distinct = list(dict.fromkeys(keys))
    receivers_by_key = dict(
        zip(
            distinct,
            routed_receivers_for_label_sets(team_id=request.team_id, label_sets=[dict(key) for key in distinct]),
        )
    )
    by_receiver: dict[UUID, tuple[RoutedReceiver, list[AnnouncedTransition]]] = {}
    for transition, key in zip(transitions, keys):
        if transition.kind.value not in request.event_ids_by_kind:
            continue
        for receiver in receivers_by_key[key]:
            if transition.kind in receiver.event_kinds:
                by_receiver.setdefault(receiver.id, (receiver, []))[1].append(transition)
    return [(receiver, tuple(heard)) for receiver, heard in by_receiver.values()]


def _deliver_to(
    routed: list[tuple[RoutedReceiver, tuple[AnnouncedTransition, ...]]],
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
    for receiver, transitions in routed:
        transport_class = _message_transport(receiver)
        if transport_class is None:
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
