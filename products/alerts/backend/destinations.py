"""Django persistence and dispatch for alert notification destinations."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q

import structlog
from prometheus_client import Counter
from rest_framework.exceptions import ValidationError

from posthog.cdp.internal_events import InternalEventEvent, flush_internal_events_producer, produce_internal_event
from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.client import ProduceResult
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers

from products.alerts.backend.destination_configs import DESTINATION_TEMPLATE_IDS, AlertDestinationConfig
from products.cdp.backend.api.hog_function import HogFunctionSerializer
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)

ALERT_INTERNAL_EVENT_DELIVERY_FAILURES = Counter(
    "posthog_alert_internal_event_delivery_failures_total",
    "Number of alert internal events that failed delivery",
    labelnames=["event_name"],
)


def create_alert_destination_hog_functions(configs: list[AlertDestinationConfig], *, request: Any) -> list[HogFunction]:
    created: list[HogFunction] = []
    hog_function_ids_by_team: dict[int, list[UUID]] = {}
    with transaction.atomic():
        for config in configs:
            team = config.team
            serializer = HogFunctionSerializer(
                data=config.payload,
                context={"request": request, "get_team": lambda team=team: team, "is_create": True},
            )
            serializer.is_valid(raise_exception=True)
            hog_function = serializer.save(team=team)
            created.append(hog_function)
            hog_function_ids_by_team.setdefault(team.id, []).append(hog_function.id)
        for team_id, hog_function_ids in hog_function_ids_by_team.items():
            _reload_hog_functions_after_commit(team_id=team_id, hog_function_ids=hog_function_ids)
    return created


def soft_delete_alert_destinations(
    *,
    team_id: int,
    alert_id: str,
    allowed_event_ids: Collection[str],
    hog_function_ids: list[UUID],
) -> None:
    unique_ids = set(hog_function_ids)
    with transaction.atomic():
        event_filter = _allowed_event_filter(allowed_event_ids)
        owned_ids = set(
            HogFunction.objects.select_for_update()
            .filter(
                event_filter,
                team_id=team_id,
                id__in=unique_ids,
                template_id__in=DESTINATION_TEMPLATE_IDS.values(),
                filters__properties__contains=[{"key": "alert_id", "value": alert_id}],
            )
            .values_list("id", flat=True)
        )
        invalid_ids = unique_ids - owned_ids
        if invalid_ids:
            formatted_ids = ", ".join(str(hog_function_id) for hog_function_id in sorted(invalid_ids, key=str))
            raise ValidationError(
                {
                    "hog_function_ids": [
                        f"These HogFunctions do not belong to this alert: {formatted_ids}. Refresh the alert and try again."
                    ]
                }
            )
        HogFunction.objects.filter(team_id=team_id, id__in=owned_ids).update(deleted=True, enabled=False)
        _reload_hog_functions_after_commit(team_id=team_id, hog_function_ids=owned_ids)


def soft_delete_all_alert_destinations(*, team_id: int, alert_id: str, allowed_event_ids: Collection[str]) -> int:
    with transaction.atomic():
        owned_ids = set(
            HogFunction.objects.select_for_update()
            .filter(
                _allowed_event_filter(allowed_event_ids),
                team_id=team_id,
                deleted=False,
                template_id__in=DESTINATION_TEMPLATE_IDS.values(),
                filters__properties__contains=[{"key": "alert_id", "value": alert_id}],
            )
            .values_list("id", flat=True)
        )
        deleted_count = HogFunction.objects.filter(team_id=team_id, id__in=owned_ids).update(
            deleted=True, enabled=False
        )
        _reload_hog_functions_after_commit(team_id=team_id, hog_function_ids=owned_ids)
        return deleted_count


def _allowed_event_filter(allowed_event_ids: Collection[str]) -> Q:
    if not allowed_event_ids:
        raise ValueError("allowed_event_ids must not be empty")

    event_filter = Q()
    for event_id in allowed_event_ids:
        event_filter |= Q(filters__events__contains=[{"id": event_id, "type": "events"}])
    return event_filter


def _reload_hog_functions_after_commit(*, team_id: int, hog_function_ids: Collection[UUID]) -> None:
    serialized_ids = sorted(str(hog_function_id) for hog_function_id in hog_function_ids)
    if serialized_ids:
        transaction.on_commit(
            lambda: reload_hog_functions_on_workers(team_id=team_id, hog_function_ids=serialized_ids),
            robust=True,
        )


def produce_alert_internal_event(
    *,
    team_id: int,
    event_name: str,
    properties: dict[str, Any],
    timestamp: datetime | None = None,
    uuid: str | None = None,
) -> ProduceResult | None:
    try:
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
    except Exception as error:
        context = {
            "alert_id": properties.get("alert_id"),
            "event_name": event_name,
            "feature": "alerts",
            "team_id": team_id,
        }
        capture_exception(error, context)
        logger.exception("Failed to enqueue alert internal event", **context)
        return None


def flush_alert_internal_events(timeout_seconds: float) -> None:
    try:
        remaining = flush_internal_events_producer(timeout_seconds)
        if remaining:
            logger.warning("Alert internal event flush timed out", remaining=remaining)
    except Exception as error:
        context = {"feature": "alerts", "phase": "notification_flush"}
        capture_exception(error, context)
        logger.exception("Failed to flush alert internal events", **context)


def alert_internal_event_delivered(
    produce_result: ProduceResult,
    *,
    team_id: int,
    alert_id: str,
    event_name: str,
) -> bool:
    try:
        produce_result.get(timeout=0)
        return True
    except Exception as error:
        context = {
            "alert_id": alert_id,
            "event_name": event_name,
            "feature": "alerts",
            "team_id": team_id,
        }
        ALERT_INTERNAL_EVENT_DELIVERY_FAILURES.labels(event_name=event_name).inc()
        logger.warning("Alert internal event was not delivered", error=str(error), **context)
        return False
