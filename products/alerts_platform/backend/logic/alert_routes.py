"""Which team-wide receivers an alert's labels route it to."""

from collections.abc import Collection, Mapping, Sequence
from typing import cast
from uuid import UUID

import structlog

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import AlertDestinationData, AlertEventKind
from products.alerts_platform.backend.models import AlertReceiver, AlertRoute, PlatformAlert

logger = structlog.get_logger(__name__)


@frozen
class RoutedReceiver:
    """One receiver a matching route sends to, with the transitions that route asked for."""

    id: UUID
    data: AlertDestinationData
    event_kinds: tuple[AlertEventKind, ...]


def matching_routes(*, team_id: int, labels: Mapping[str, str]) -> list[AlertRoute]:
    """Every enabled route to an enabled receiver that these labels match, in route order, up to
    the first match that stops matching."""
    return _first_matches(_enabled_routes(team_id), labels)


def routed_receivers(*, team_id: int, labels: Mapping[str, str]) -> tuple[RoutedReceiver, ...]:
    """The receivers of every route `matching_routes` finds, in route order.

    A receiver that two routes reach is sent to once, with the kinds of both.
    """
    return routed_receivers_for_label_sets(team_id=team_id, label_sets=[labels])[0]


def has_enabled_routes(team_id: int) -> bool:
    return AlertRoute.objects.for_team(team_id).filter(enabled=True, receiver__enabled=True).exists()


def stored_group_labels(
    *, team_id: int, configuration_id: str, grouping_keys: Collection[str]
) -> dict[str, dict[str, str]]:
    """The labels each group's instance last kept. A group a check stopped returning resolves
    without labels, and its instance still holds the ones its firing had."""
    if not grouping_keys:
        return {}
    rows = (
        PlatformAlert.objects.for_team(team_id)
        .filter(configuration_id=configuration_id, grouping_key__in=grouping_keys)
        .values_list("grouping_key", "labels")
    )
    return {grouping_key: dict(labels or {}) for grouping_key, labels in rows}


def routing_labels(*, group_labels: Mapping[str, str], rule_labels: Mapping[str, str]) -> dict[str, str]:
    """The labels a group's transition is routed on: the group's own labels with the rule's
    labels on top, so a rule label wins over a group label of the same name, as in Prometheus."""
    return {**group_labels, **rule_labels}


def routed_receivers_for_label_sets(
    *, team_id: int, label_sets: Sequence[Mapping[str, str]]
) -> list[tuple[RoutedReceiver, ...]]:
    """`routed_receivers` for each label set, in the same order, reading the team's routes once."""
    routes = _enabled_routes(team_id)
    kinds_per_set = [_kinds_by_receiver(_first_matches(routes, labels)) for labels in label_sets]
    matched_ids = {receiver_id for kinds in kinds_per_set for receiver_id in kinds}
    # Loaded only for the receivers that matched, so a team's other configs are never decrypted.
    configs = (
        {
            receiver.id: receiver.config
            for receiver in AlertReceiver.objects.for_team(team_id).filter(id__in=matched_ids).only("id", "config")
        }
        if matched_ids
        else {}
    )
    return [
        tuple(
            RoutedReceiver(
                id=receiver_id, data=cast(AlertDestinationData, configs[receiver_id]), event_kinds=tuple(kinds)
            )
            for receiver_id, kinds in kinds_by_receiver.items()
            if receiver_id in configs
        )
        for kinds_by_receiver in kinds_per_set
    ]


def _enabled_routes(team_id: int) -> list[AlertRoute]:
    return list(
        AlertRoute.objects.for_team(team_id)
        .filter(enabled=True, receiver__enabled=True)
        .order_by("position", "created_at", "id")
    )


def _first_matches(routes: Sequence[AlertRoute], labels: Mapping[str, str]) -> list[AlertRoute]:
    matched: list[AlertRoute] = []
    for route in routes:
        if not _matches(route, labels):
            continue
        matched.append(route)
        if not route.continue_matching:
            break
    return matched


def _kinds_by_receiver(routes: Sequence[AlertRoute]) -> dict[UUID, dict[AlertEventKind, None]]:
    kinds_by_receiver: dict[UUID, dict[AlertEventKind, None]] = {}
    for route in routes:
        kinds_by_receiver.setdefault(route.receiver_id, {}).update(
            dict.fromkeys(AlertEventKind(kind) for kind in route.event_kinds)
        )
    return kinds_by_receiver


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
