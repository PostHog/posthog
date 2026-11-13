"""Which team-wide receivers an alert's labels route it to."""

from collections.abc import Mapping
from typing import cast
from uuid import UUID

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts_platform.backend.delivery.team_flags import team_flag_enabled
from products.alerts_platform.backend.facade.contracts import ROUTING_FLAG, AlertDestinationData, AlertEventKind
from products.alerts_platform.backend.logic.alert_destinations import INCIDENT_DESTINATION_TYPES
from products.alerts_platform.backend.models import AlertReceiver, AlertRoute, PlatformAlertConfiguration

logger = structlog.get_logger(__name__)


def routing_is_enabled(team: Team) -> bool:
    """Fail closed, so a flag-eval blip sends to the alert's own destinations only."""
    try:
        return bool(team_flag_enabled(ROUTING_FLAG, team))
    except Exception:
        logger.warning("alerts_platform_routing_flag_check_failed_defaulting_off", team_id=team.id, exc_info=True)
        return False


@frozen
class RoutedReceiver:
    """One receiver a matching route sends to, with the transitions that route asked for."""

    id: UUID
    data: AlertDestinationData
    event_kinds: tuple[AlertEventKind, ...]


def matching_routes(*, team_id: int, labels: Mapping[str, str]) -> list[AlertRoute]:
    """Every enabled route to an enabled receiver that these labels match, in route order, up to
    the first match that stops matching."""
    matched: list[AlertRoute] = []
    routes = (
        AlertRoute.objects.for_team(team_id)
        .filter(enabled=True, receiver__enabled=True)
        .order_by("position", "created_at", "id")
    )
    for route in routes:
        if not _matches(route, labels):
            continue
        matched.append(route)
        if not route.continue_matching:
            break
    return matched


def routed_receivers(*, team_id: int, labels: Mapping[str, str]) -> tuple[RoutedReceiver, ...]:
    """The receivers of every route `matching_routes` finds, in route order.

    A receiver that two routes reach is sent to once, with the kinds of both.
    """
    kinds_by_receiver: dict[UUID, dict[AlertEventKind, None]] = {}
    for route in matching_routes(team_id=team_id, labels=labels):
        kinds_by_receiver.setdefault(route.receiver_id, {}).update(
            dict.fromkeys(AlertEventKind(kind) for kind in route.event_kinds)
        )
    # Loaded only for the receivers that matched, so a team's other configs are never decrypted.
    configs = {
        receiver.id: receiver.config
        for receiver in AlertReceiver.objects.for_team(team_id).filter(id__in=kinds_by_receiver).only("id", "config")
    }
    return tuple(
        RoutedReceiver(id=receiver_id, data=cast(AlertDestinationData, configs[receiver_id]), event_kinds=tuple(kinds))
        for receiver_id, kinds in kinds_by_receiver.items()
        if receiver_id in configs
    )


def _routing_may_be_enabled(team: Team) -> bool:
    """Fails open, unlike `routing_is_enabled`. A trigger or resolve dropped here is gone for good, while
    keeping one costs at most a delivery that routing then declines."""
    try:
        return team_flag_enabled(ROUTING_FLAG, team) is not False
    except Exception:
        logger.warning(
            "alerts_platform_routing_flag_check_failed_keeping_incident_actions", team_id=team.id, exc_info=True
        )
        return True


def has_incident_receiver(team_id: int) -> bool:
    """Whether the team has an enabled incident manager receiver. Most teams have none, and this answers
    that without a flag evaluation or a decrypt."""
    return AlertReceiver.objects.for_team(team_id).filter(type__in=INCIDENT_DESTINATION_TYPES, enabled=True).exists()


def routes_reach_incident_receiver(*, team_id: int, configuration_id: UUID) -> bool:
    """Whether a route this alert matches sends to an incident manager, so that a firing that opens
    or closes needs a delivery even when the alert has no incident manager of its own."""
    if not has_incident_receiver(team_id):
        return False
    team = Team.objects.filter(id=team_id).first()
    if team is None or not _routing_may_be_enabled(team):
        return False
    labels = (
        PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(id=configuration_id)
        .values_list("labels", flat=True)
        .first()
    )
    return any(
        receiver.data.get("type") in INCIDENT_DESTINATION_TYPES
        for receiver in routed_receivers(team_id=team_id, labels=labels or {})
    )


def _matches(route: AlertRoute, labels: Mapping[str, str]) -> bool:
    return all(_holds(route, matcher, labels) for matcher in route.matchers)


def _holds(route: AlertRoute, matcher: object, labels: Mapping[str, str]) -> bool:
    # Only equality for now. A route with any other matcher sends nothing rather than sending
    # everywhere, and the warning makes the gap visible.
    if not isinstance(matcher, dict) or matcher.get("op") != "=":
        logger.warning("alerts_platform_route_matcher_unsupported", route_id=str(route.id), matcher=matcher)
        return False
    label = matcher.get("label")
    return isinstance(label, str) and labels.get(label) == matcher.get("value")
