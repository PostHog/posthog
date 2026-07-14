"""Django persistence and dispatch for alert notification destinations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.kafka_client.client import ProduceResult

from products.alerts.backend.destination_configs import AlertDestinationConfig, AlertDestinationTemplate
from products.cdp.backend.api.hog_function import HogFunctionSerializer
from products.cdp.backend.models.hog_functions.hog_function import HogFunction


class AlertDestinationOwnershipError(Exception):
    def __init__(self, invalid_hog_function_ids: set[UUID]) -> None:
        self.invalid_hog_function_ids = tuple(sorted(invalid_hog_function_ids, key=str))
        super().__init__()


def create_alert_destination_hog_functions(configs: list[AlertDestinationConfig], *, request: Any) -> list[HogFunction]:
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
    unique_ids = set(hog_function_ids)
    with transaction.atomic():
        owned_ids = set(
            HogFunction.objects.select_for_update()
            .filter(
                team_id=team_id,
                id__in=unique_ids,
                template_id__in=list(AlertDestinationTemplate),
                filters__properties__contains=[{"key": "alert_id", "value": alert_id}],
            )
            .values_list("id", flat=True)
        )
        invalid_ids = unique_ids - owned_ids
        if invalid_ids:
            raise AlertDestinationOwnershipError(invalid_ids)
        HogFunction.objects.filter(team_id=team_id, id__in=owned_ids).update(deleted=True, enabled=False)


def soft_delete_all_alert_destinations(*, team_id: int, alert_id: str) -> int:
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
