"""Django persistence and dispatch for alert notification destinations."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet

import structlog
from prometheus_client import Counter
from rest_framework.exceptions import ValidationError

from posthog.cdp.internal_events import InternalEventEvent, flush_internal_events_producer, produce_internal_event
from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.client import ProduceResult
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers

from products.alerts.backend.destination_configs import DESTINATION_TEMPLATE_IDS, AlertDestinationConfig
from products.alerts.backend.models.alert_identity import AlertDestination, AlertIdentity, AlertProduct
from products.cdp.backend.api.hog_function import HogFunctionSerializer
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)

ALERT_NOTIFICATION_FLUSH_TIMEOUT_SECONDS = 10.0

ALERT_INTERNAL_EVENT_DELIVERY_FAILURES = Counter(
    "posthog_alert_internal_event_delivery_failures_total",
    "Number of alert internal events that failed delivery",
    labelnames=["event_name"],
)


@dataclass(frozen=True, kw_only=True)
class AlertDelivery:
    """Receipt for one destination that accepted a send. `status` is an open set, so a
    future transport can report an outcome other than "accepted"."""

    channel: str  # "email" | "hog_function"
    target: str  # email address or destination name
    target_id: str | None = None  # hog function id
    template: str | None = None  # "slack" | "discord" | "webhook" | "teams"
    status: str = "accepted"
    at: str  # ISO-8601 timestamp


def serialize_deliveries(deliveries: Sequence[AlertDelivery]) -> list[dict[str, Any]]:
    return [asdict(delivery) for delivery in deliveries]


@dataclass(frozen=True, kw_only=True)
class ActiveAlertDestination:
    id: str
    name: str
    destination_type: str | None


_TEMPLATE_ID_TO_DESTINATION_TYPE = {
    template_id: destination_type.value for destination_type, template_id in DESTINATION_TEMPLATE_IDS.items()
}


def _active_alert_destinations_qs(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> QuerySet[HogFunction]:
    return HogFunction.objects.filter(
        _allowed_event_filter(allowed_event_ids),
        team_id=team_id,
        deleted=False,
        enabled=True,
        template_id__in=DESTINATION_TEMPLATE_IDS.values(),
        filters__properties__contains=[{"key": "alert_id", "value": alert_id}],
    )


def get_or_create_alert_identity(
    *,
    product: AlertProduct,
    organization_id: UUID,
    execution_team_id: int | None,
    alert_id: UUID,
) -> AlertIdentity:
    """Return the shared identity for one product alert, creating it on first use.

    Reuses the product alert's own UUID so API identifiers and internal-event
    `alert_id` properties stay stable across the migration.
    """
    alert_identity, _ = AlertIdentity.objects.get_or_create(
        id=alert_id,
        defaults={
            "product": product,
            "organization_id": organization_id,
            "execution_team_id": execution_team_id,
        },
    )
    return alert_identity


def create_alert_destination_hog_functions(configs: list[AlertDestinationConfig], *, request: Any) -> list[HogFunction]:
    created: list[HogFunction] = []
    hog_function_ids_by_team: dict[int, list[UUID]] = {}
    with transaction.atomic():
        for config in configs:
            team = config.team
            serializer = HogFunctionSerializer(
                data=config.payload,
                context={
                    "request": request,
                    "get_team": lambda team=team: team,
                    "is_create": True,
                    "allow_managed_alert_destination": True,
                },
            )
            serializer.is_valid(raise_exception=True)
            hog_function = serializer.save(team=team)
            created.append(hog_function)
            hog_function_ids_by_team.setdefault(team.id, []).append(hog_function.id)
        for team_id, hog_function_ids in hog_function_ids_by_team.items():
            _reload_hog_functions_after_commit(team_id=team_id, hog_function_ids=hog_function_ids)
    return created


def create_owned_alert_destination(
    configs: list[tuple[AlertDestinationConfig, str]],
    *,
    request: Any,
    alert_identity: AlertIdentity,
    destination_type: str,
    destination_name: str,
) -> list[HogFunction]:
    """Create one logical AlertDestination plus its executors, stamping ownership.

    `configs` pairs each `AlertDestinationConfig` with its event kind (e.g.
    "firing"), so the executors are linked to the AlertDestination and typed by
    kind instead of relying solely on JSON filters. Used during Phase 3 dual-write.
    """
    destination = AlertDestination.objects.create(
        alert=alert_identity,
        type=destination_type,
        name=destination_name,
    )
    created: list[HogFunction] = []
    hog_function_ids_by_team: dict[int, list[UUID]] = {}
    with transaction.atomic():
        for config, event_kind in configs:
            team = config.team
            payload = {
                **config.payload,
                "alert_destination": str(destination.id),
                "alert_event_kind": event_kind,
            }
            serializer = HogFunctionSerializer(
                data=payload,
                context={
                    "request": request,
                    "get_team": lambda team=team: team,
                    "is_create": True,
                    "allow_managed_alert_destination": True,
                },
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
        owned_rows = list(
            HogFunction.objects.select_for_update()
            .filter(
                event_filter,
                team_id=team_id,
                deleted=False,
                template_id__in=DESTINATION_TEMPLATE_IDS.values(),
                filters__properties__contains=[{"key": "alert_id", "value": alert_id}],
            )
            .values_list("id", "template_id", "filters")
        )
        owned_ids = {hog_function_id for hog_function_id, _, _ in owned_rows}
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

        allowed_events = set(allowed_event_ids)
        rows_by_template: dict[str | None, list[tuple[UUID, str | None]]] = {}
        for hog_function_id, template_id, filters in owned_rows:
            event_id = next(
                (
                    event_filter.get("id")
                    for event_filter in (filters or {}).get("events", [])
                    if isinstance(event_filter, dict) and event_filter.get("type") == "events"
                ),
                None,
            )
            rows_by_template.setdefault(template_id, []).append((hog_function_id, event_id))

        for group in rows_by_template.values():
            group_ids = {hog_function_id for hog_function_id, _ in group}
            if not unique_ids.intersection(group_ids):
                continue
            if group_ids != unique_ids.intersection(group_ids) or {event_id for _, event_id in group} != allowed_events:
                raise ValidationError(
                    {"hog_function_ids": ["Delete every HogFunction in the destination group together."]}
                )

        HogFunction.objects.filter(team_id=team_id, id__in=unique_ids).update(deleted=True, enabled=False)
        _reload_hog_functions_after_commit(team_id=team_id, hog_function_ids=unique_ids)


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


def soft_delete_alert_destinations_for_alerts(
    *, team_id: int, alert_ids: Collection[str], allowed_event_ids: Collection[str]
) -> int:
    """Soft-delete alert-owned destinations in bulk when their execution team is removed."""
    event_filter = _allowed_event_filter(allowed_event_ids)
    if not alert_ids:
        return 0
    destination_ids: set[UUID] = set()
    with transaction.atomic():
        alert_id_filter = Q(pk__in=[])
        for alert_id in alert_ids:
            alert_id_filter |= Q(filters__properties__contains=[{"key": "alert_id", "value": alert_id}])
        destination_ids = set(
            HogFunction.objects.select_for_update()
            .filter(
                alert_id_filter,
                event_filter,
                team_id=team_id,
                deleted=False,
                template_id__in=DESTINATION_TEMPLATE_IDS.values(),
            )
            .values_list("id", flat=True)
        )
        deleted_count = HogFunction.objects.filter(team_id=team_id, id__in=destination_ids).update(
            deleted=True, enabled=False
        )
        _reload_hog_functions_after_commit(team_id=team_id, hog_function_ids=destination_ids)
        return deleted_count


def count_active_alert_destinations(*, team_id: int, alert_id: str, allowed_event_ids: Collection[str]) -> int:
    return _active_alert_destinations_qs(
        team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids
    ).count()


# Webhook-style destination names embed the full webhook URL, whose path is a channel
# credential (Slack/Discord/Teams webhook secret). Receipts flow into the API and the
# History tooltip, so keep only the host.
_URL_IN_NAME_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)

_DESTINATION_NAME_SEPARATOR = " → "


def _url_host(match: re.Match[str]) -> str:
    # hostname, not the raw authority: it drops any user:password@ prefix.
    try:
        return urlsplit(match.group(0)).hostname or "destination"
    except ValueError:
        return "destination"


def _receipt_safe_name(name: str) -> str:
    return _URL_IN_NAME_RE.sub(_url_host, name)


def _destination_display_name(name: str) -> str:
    # Names read "<product> — <alert> (<kind>) → <destination>"; keep the trailing
    # segment. rpartition, since an alert name may contain the separator too.
    _, _, destination = name.rpartition(_DESTINATION_NAME_SEPARATOR)
    return _receipt_safe_name(destination or name)


def list_active_alert_destinations(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> list[ActiveAlertDestination]:
    rows = _active_alert_destinations_qs(
        team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids
    ).values_list("id", "name", "template_id")
    destinations = []
    for hog_function_id, name, template_id in rows:
        destination_type = _TEMPLATE_ID_TO_DESTINATION_TYPE.get(template_id) if template_id else None
        destinations.append(
            ActiveAlertDestination(
                id=str(hog_function_id),
                name=_destination_display_name(name) if name else "Destination",
                destination_type=destination_type,
            )
        )
    return destinations


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
