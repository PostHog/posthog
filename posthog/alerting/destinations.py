"""Shared persistence and dispatch mechanics for alert notification destinations.

The pure config builders live in common/alerting/destinations.py; this module owns
the Django/CDP side every alerting product otherwise duplicates: creating the
HogFunctions through HogFunctionSerializer (so template lookup and bytecode
compilation run), ownership-checked soft deletion, and producing the internal
event that CDP destinations consume.

CDP exposes no facade today, so this is deliberately the one place that hand-drives
HogFunctionSerializer for alerts — when a CDP facade lands, only this module moves.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.kafka_client.client import ProduceResult

from products.cdp.backend.api.hog_function import HogFunctionSerializer
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

from common.alerting.destinations import ALERT_ID_PROPERTY, DESTINATION_TYPE_BY_TEMPLATE_ID, AlertDestinationConfig


class AlertDestinationOwnershipError(Exception):
    """Raised when deleting destinations that do not all belong to an alert."""


def create_alert_destination_hog_functions(configs: list[AlertDestinationConfig], *, request: Any) -> list[HogFunction]:
    """Create one HogFunction per config, atomically."""
    created: list[HogFunction] = []
    with transaction.atomic():
        for config in configs:
            team = config.team
            serializer = HogFunctionSerializer(
                data=config.payload,
                context={"request": request, "get_team": lambda team=team: team, "is_create": True},
            )
            serializer.is_valid(raise_exception=True)
            created.append(serializer.save(team=team))
    return created


def soft_delete_alert_destinations(
    *,
    team_id: int,
    alert_id: str,
    hog_function_ids: list[UUID],
) -> None:
    """Soft-delete a destination's HogFunction group, verifying every ID belongs to the alert.

    The filtered UPDATE is the ownership check: touching fewer rows than requested
    means something in the list doesn't belong to this alert — roll back. Narrowed
    to `template_id__in=DESTINATION_TYPE_BY_TEMPLATE_ID`, matching the delete-all
    path below, so a same-team HogFunction that isn't an alert destination can't
    be soft-deleted just because it happens to carry a matching `alert_id`
    property (e.g. an unrelated automation reusing that property key).

    Unlike the delete-all path below, this deliberately does not filter on
    `deleted=False`: already-deleted rows still count as owned, keeping a retried
    delete idempotent instead of tripping the ownership check.
    """
    unique_ids = set(hog_function_ids)
    with transaction.atomic():
        updated = HogFunction.objects.filter(
            team_id=team_id,
            id__in=unique_ids,
            template_id__in=list(DESTINATION_TYPE_BY_TEMPLATE_ID),
            filters__properties__contains=[{"key": ALERT_ID_PROPERTY, "value": alert_id}],
        ).update(deleted=True, enabled=False)
        if updated != len(unique_ids):
            raise AlertDestinationOwnershipError


def soft_delete_all_alert_destinations(*, team_id: int, alert_id: str) -> int:
    """Soft-delete every destination HogFunction linked to an alert (alert deletion path)."""
    return HogFunction.objects.filter(
        team_id=team_id,
        deleted=False,
        template_id__in=list(DESTINATION_TYPE_BY_TEMPLATE_ID),
        filters__properties__contains=[{"key": ALERT_ID_PROPERTY, "value": alert_id}],
    ).update(deleted=True, enabled=False)


def produce_alert_internal_event(
    *,
    team_id: int,
    event_name: str,
    properties: dict[str, Any],
    timestamp: datetime | None = None,
    uuid: str | None = None,
) -> ProduceResult:
    """Produce the internal event CDP destinations consume. Callers own error handling.

    Returns the pending Kafka delivery so callers can confirm it (``.get()``) or
    treat a raised exception as an enqueue failure.
    """
    return produce_internal_event(
        team_id=team_id,
        event=InternalEventEvent(
            event=event_name,
            distinct_id=f"team_{team_id}",
            properties=properties,
            timestamp=timestamp.isoformat() if timestamp else None,
            uuid=uuid,
        ),
    )
