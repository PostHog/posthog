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

from common.alerting.destinations import AlertDestinationConfig, AlertDestinationTemplate


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
    """Soft-delete destinations after verifying every ID belongs to the alert.

    Already-deleted destinations count as owned so retries remain idempotent.
    """
    unique_ids = set(hog_function_ids)
    with transaction.atomic():
        updated = HogFunction.objects.filter(
            team_id=team_id,
            id__in=unique_ids,
            template_id__in=list(AlertDestinationTemplate),
            filters__properties__contains=[{"key": "alert_id", "value": alert_id}],
        ).update(deleted=True, enabled=False)
        if updated != len(unique_ids):
            raise AlertDestinationOwnershipError


def soft_delete_all_alert_destinations(*, team_id: int, alert_id: str) -> int:
    """Soft-delete every destination HogFunction linked to an alert (alert deletion path)."""
    return HogFunction.objects.filter(
        team_id=team_id,
        deleted=False,
        template_id__in=list(AlertDestinationTemplate),
        filters__properties__contains=[{"key": "alert_id", "value": alert_id}],
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
