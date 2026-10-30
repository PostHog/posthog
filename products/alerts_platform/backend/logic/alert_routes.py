"""Which team-wide receivers an alert's labels route it to."""

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

import structlog

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import AlertDestinationData, AlertEventKind
from products.alerts_platform.backend.models import AlertReceiver, AlertRoute

logger = structlog.get_logger(__name__)


@frozen
class RoutedReceiver:
    """One receiver a matching route sends to, with the transitions that route asked for."""

    id: UUID
    data: AlertDestinationData
    event_kinds: tuple[AlertEventKind, ...]


def routed_receivers(*, team_id: int, labels: Mapping[str, str]) -> tuple[RoutedReceiver, ...]:
    """The receivers of every enabled route these labels match, in route order.

    A receiver that two routes reach is sent to once, with the kinds of both.
    """
    routes = (
        AlertRoute.objects.for_team(team_id)
        .filter(enabled=True, receiver__enabled=True)
        .order_by("position", "created_at", "id")
    )
    kinds_by_receiver: dict[UUID, dict[AlertEventKind, None]] = {}
    for route in routes:
        if not _matches(route, labels):
            continue
        kinds_by_receiver.setdefault(route.receiver_id, {}).update(
            dict.fromkeys(AlertEventKind(kind) for kind in route.event_kinds)
        )
        if not route.continue_matching:
            break
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


def _matches(route: AlertRoute, labels: Mapping[str, str]) -> bool:
    return all(_holds(route, matcher, labels) for matcher in route.matchers)


def _holds(route: AlertRoute, matcher: Any, labels: Mapping[str, str]) -> bool:
    # Only equality for now. A route with any other matcher sends nothing rather than sending
    # everywhere, and the warning makes the gap visible.
    if not isinstance(matcher, dict) or matcher.get("op") != "=":
        logger.warning("alerts_platform_route_matcher_unsupported", route_id=str(route.id), matcher=matcher)
        return False
    label = matcher.get("label")
    return isinstance(label, str) and labels.get(label) == matcher.get("value")
