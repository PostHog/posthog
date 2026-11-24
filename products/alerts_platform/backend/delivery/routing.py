"""Sends an evaluation's messages and incident events to the team-wide receivers whose routes match each group's labels.

Runs in its own activity, after the alert's own destinations have had their sends, so a receiver
that fails retries on its own and can never cost those destinations their message.
"""

from dataclasses import replace
from uuid import UUID

import structlog

from posthog.models import Team
from posthog.utils import absolute_uri

from products.alerts_platform.backend.delivery.dispatch import SendTally, deliver
from products.alerts_platform.backend.delivery.evaluation import _TRANSPORTS, announcement_to_deliver
from products.alerts_platform.backend.delivery.team_flags import team_flag_enabled
from products.alerts_platform.backend.delivery.thread_store import DatabaseThreadStore
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.facade.contracts import (
    ROUTING_FLAG,
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
    has_enabled_routes,
    has_incident_route,
    routed_receivers_for_label_sets,
    routing_labels,
    stored_group_labels,
)
from products.alerts_platform.backend.logic.platform_reads import rule_metadata

logger = structlog.get_logger(__name__)


def _routing_flag(team: Team) -> bool | None:
    """None when the flag could not be evaluated."""
    try:
        return team_flag_enabled(ROUTING_FLAG, team)
    except Exception:
        logger.warning("alerts_platform_routing_flag_check_failed", team_id=team.id, exc_info=True)
        return None


def _routing_is_enabled(team: Team, request: AlertDeliveryRequest) -> bool:
    """Fail closed for messages, so a flag-eval blip sends to the alert's own destinations only.

    A routed incident receiver that missed a resolve would keep its incident open until someone closed
    it by hand, so a delivery with incident actions raises instead and the activity retries it.
    """
    enabled = _routing_flag(team)
    if enabled is None and request.incident_actions and has_incident_route(request.team_id):
        raise DeliveryError("The alert routing flag could not be evaluated.")
    return bool(enabled)


def _opens_incidents(receiver: RoutedReceiver) -> bool:
    return receiver.data.get("type") in INCIDENT_DESTINATION_TYPES


def _routing_team(request: AlertDeliveryRequest) -> Team | None:
    if not request.owned_by_platform:
        return None
    # A delivery that exists only for its incident actions has nothing for a chat receiver.
    if not request.sends_messages and not has_incident_route(request.team_id):
        return None
    team = Team.objects.filter(id=request.team_id).first()
    if team is None or not _routing_is_enabled(team, request):
        return None
    if delivery_holds.blocks_delivery(request.team_id, request.configuration_id, request.evaluation_key):
        return None
    return team


def deliver_routes(request: AlertDeliveryRequest) -> int:
    """How many receivers were sent to. A chat receiver hears the transitions its routes asked for,
    and an incident manager hears every trigger and resolve, whatever kinds its routes list: one that
    heard a trigger and not its resolve would keep the incident open.

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
    pages = any(_opens_incidents(receiver) for receiver, _ in routed)
    if pages and (stale := delivery_holds.stale_held_triggers(request, announced.transitions)):
        request = replace(
            request,
            incident_actions={key: action for key, action in request.incident_actions.items() if key not in stale},
        )
    return _deliver_to(routed, request=request, team=team, announced=replace(announced, rule=rule))


def _routed_transitions(
    request: AlertDeliveryRequest,
    *,
    rule_labels: dict[str, str],
    transitions: tuple[AnnouncedTransition, ...],
) -> list[tuple[RoutedReceiver, tuple[AnnouncedTransition, ...]]]:
    """Each matched receiver with the transitions it hears, in route order of first match."""
    stored = stored_group_labels(
        team_id=request.team_id,
        configuration_id=request.configuration_id,
        grouping_keys={transition.grouping_key for transition in transitions if not transition.labels},
    )
    keys = [
        tuple(
            sorted(
                routing_labels(
                    group_labels=transition.labels or stored.get(transition.grouping_key, {}),
                    rule_labels=rule_labels,
                ).items()
            )
        )
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
        for receiver in receivers_by_key[key]:
            if _hears(receiver, transition, request):
                by_receiver.setdefault(receiver.id, (receiver, []))[1].append(transition)
    return [(receiver, tuple(heard)) for receiver, heard in by_receiver.values()]


def _hears(receiver: RoutedReceiver, transition: AnnouncedTransition, request: AlertDeliveryRequest) -> bool:
    """An incident manager hears every group whose firing opened or closed. A chat receiver hears the
    kinds its routes asked for, a follow-up as the firing it follows, and nothing on a delivery that
    exists only for incident actions."""
    if _opens_incidents(receiver):
        action = request.incident_actions.get(transition.grouping_key)
        return action is not None and action.value in request.event_ids_by_incident_action
    return (
        request.sends_messages
        and transition.kind.value in request.event_ids_by_kind
        and transition.kind.delivered_as in receiver.event_kinds
    )


def _sends(
    receiver: RoutedReceiver, transitions: tuple[AnnouncedTransition, ...], request: AlertDeliveryRequest
) -> list[tuple[tuple[AnnouncedTransition, ...], IncidentAction | None]]:
    """The sends one receiver gets: one per incident action for an incident manager, else one message send."""
    if not _opens_incidents(receiver):
        return [(transitions, None)]
    sends = [
        (tuple(t for t in transitions if request.incident_actions.get(t.grouping_key) == action), action)
        for action in IncidentAction
    ]
    return [(heard, action) for heard, action in sends if heard]


def _deliver_to(
    routed: list[tuple[RoutedReceiver, tuple[AnnouncedTransition, ...]]],
    *,
    request: AlertDeliveryRequest,
    team: Team,
    announced: EvaluationAnnouncement,
) -> int:
    thread_store = DatabaseThreadStore(request.team_id)
    project = MessageLink(label=team.name, url=absolute_uri(f"/project/{team.id}"))
    tally = SendTally()
    for receiver, transitions in routed:
        transport_class = _TRANSPORTS.get(receiver.data.get("type"))
        if transport_class is None:
            continue
        # Each send fails on its own, so a refused trigger cannot cost another group its resolve.
        problems = tally.problems
        for heard, action in _sends(receiver, transitions, request):
            with tally.attempt(counted=False):
                deliver(
                    transport=transport_class(),
                    thread_store=thread_store,
                    team_id=request.team_id,
                    configuration_id=request.configuration_id,
                    evaluation_key=request.evaluation_key,
                    target=receiver.data,
                    destination_id=str(receiver.id),
                    announcement=replace(announced, transitions=heard, overflowed=0),
                    incident_action=action,
                    source_alert_url=request.source_alert_url,
                    project=project,
                )
        if tally.problems == problems:
            tally.sent += 1
    tally.raise_failures("send")
    return tally.sent
