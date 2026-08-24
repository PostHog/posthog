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
from products.alerts.backend.models.shared_alert import AlertDestination, AlertSharedIdentity
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


def get_or_create_shared_alert(
    *,
    alert_id: UUID,
    product: str,
    organization_id: UUID,
    execution_team_id: int | None,
) -> AlertSharedIdentity:
    """Return the shared identity row for one product alert, creating it on
    first use with the product alert's UUID as the primary key.

    Callers pass the product row's UUID so the API URLs, internal events, and
    history that already reference the alert keep pointing at the same
    identifier after the migration backfills and links remain stable.
    """
    shared_alert, created = AlertSharedIdentity.objects.get_or_create(
        id=alert_id,
        defaults={
            "product": product,
            "organization_id": organization_id,
            "execution_team_id": execution_team_id,
        },
    )
    if not created:
        # The product row may have moved teams since the backfill; keep the
        # execution team in sync so routing and authorization don't drift.
        update_fields: list[str] = []
        if shared_alert.execution_team_id != execution_team_id:
            shared_alert.execution_team_id = execution_team_id
            update_fields.append("execution_team_id")
        if shared_alert.organization_id != organization_id:
            shared_alert.organization_id = organization_id
            update_fields.append("organization_id")
        if update_fields:
            shared_alert.save(update_fields=update_fields)
    return shared_alert


def delete_shared_alert_destinations(*, shared_alert: AlertSharedIdentity) -> int:
    """Soft-delete the HogFunction executors owned by every destination of
    this alert, with CDP worker cache reload.

    Call this when the user deletes a destination group or an alert: the Hog
    functions move to `deleted=True` so history and revision APIs keep the
    rows, while the AlertDestination rows stay for audit and so the runtime
    sees the removal through cache invalidation. The DB cascade from
    `AlertSharedIdentity → AlertDestination → HogFunction` still hard-deletes
    when the alert row itself is deleted.
    """
    executors_by_team: dict[int, list[UUID]] = {}
    destination_ids = list(shared_alert.destinations.values_list("id", flat=True))
    if not destination_ids:
        return 0

    with transaction.atomic():
        owned_rows = HogFunction.objects.select_for_update().filter(
            alert_destination_id__in=destination_ids, deleted=False
        )
        deleted_count = 0
        for executor in owned_rows:
            executor.deleted = True
            executor.enabled = False
            executor.save(update_fields=["deleted", "enabled", "updated_at"])
            executors_by_team.setdefault(executor.team_id, []).append(executor.id)
            deleted_count += 1

        for team_id, hog_function_ids in executors_by_team.items():
            _reload_hog_functions_after_commit(team_id=team_id, hog_function_ids=hog_function_ids)

        return deleted_count


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


def create_alert_destination_hog_functions(
    configs: list[AlertDestinationConfig],
    *,
    request: Any,
    shared_alert: AlertSharedIdentity | None = None,
    destination_name: str | None = None,
) -> list[HogFunction]:
    """Create one HogFunction per config — one logical destination across the
    alert's event kinds — and, when `shared_alert` is given, record explicit
    ownership.

    With `shared_alert`, a single `AlertDestination` row points at this logical
    group, each saved HogFunction gets `alert_destination` and `alert_event_kind`
    set, and the relationship is enforced in the DB (with the `.unique` /
    `.check` constraints on `posthog_hogfunction`). The payload's `filters` still
    carries the `alert_id`/event pair during dual-write so the runtime keeps
    matching before the managed-alert switch-over.

    `destination_name` labels the shared row (the user's snippet of Slack
    channel / webhook host); when omitted the group uses the first config's
    HogFunction name, which includes the product label and the alert name.
    """
    created: list[HogFunction] = []
    hog_function_ids_by_team: dict[int, list[UUID]] = {}

    # Today callers submit one logical destination per call: every config carries
    # the same destination type and team. Guard against splitting one logical
    # destination across rows (or bloating one AlertDestination with several
    # destinations) if that ever changes.
    if shared_alert is not None:
        destinations_types = {config.payload.get("template_id") for config in configs}
        destinations_teams = {config.team.id for config in configs}
        if len(destinations_types) > 1 or len(destinations_teams) > 1:
            raise ValidationError(
                {
                    "configs": [
                        "create_alert_destination_hog_functions accepts one logical destination "
                        "(single template_id, single team) per call when shared_alert is set."
                    ]
                }
            )
        kinds = [config.alert_event_kind for config in configs]
        if len(kinds) != len(set(kinds)):
            raise ValidationError(
                {"configs": ["alert_event_kind values must be unique within one logical destination."]}
            )

    with transaction.atomic():
        destination: AlertDestination | None = None
        if shared_alert is not None:
            destination_type_value = None
            if configs and configs[0].payload.get("template_id"):
                destination_type_value = _TEMPLATE_ID_TO_DESTINATION_TYPE.get(configs[0].payload.get("template_id"))
            if destination_type_value is None:
                raise ValidationError(
                    {"template_id": ["Unknown alert destination template; cannot determine destination type."]}
                )
            destination = AlertDestination.objects.create(
                shared_alert=shared_alert,
                type=destination_type_value,
                name=destination_name or (configs[0].payload.get("name") if configs else "") or "",
            )

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
            if destination is not None:
                # Bypass the serializer to stamp explicit ownership; the
                # serializer's validation must not need to know about the
                # internal executor columns.
                HogFunction.objects.filter(id=hog_function.id).update(
                    alert_destination=destination,
                    alert_event_kind=config.alert_event_kind,
                )
                hog_function.refresh_from_db(fields=["alert_destination", "alert_event_kind"])
            created.append(hog_function)
            hog_function_ids_by_team.setdefault(team.id, []).append(hog_function.id)
        for team_id, hog_function_ids in hog_function_ids_by_team.items():
            _reload_hog_functions_after_commit(team_id=team_id, hog_function_ids=hog_function_ids)
    return created


def soft_delete_alert_destinations_by_ids(
    *,
    team_id: int,
    alert_destination_ids: Collection[UUID],
) -> int:
    """Soft-delete every HogFunction owned by the given AlertDestination rows.

    Caller confirms the destination belongs to a valid alert before deleting
    (the destination row itself lives behind the owning alert's authorization
    and is usually deleted in the same transaction). Ownership is the typed
    `alert_destination` FK, not the JSON filter — this is the eventual
    replacement for `soft_delete_alert_destinations` once the dual-write window
    closes.
    """
    if not alert_destination_ids:
        return 0
    with transaction.atomic():
        owned_ids = set(
            HogFunction.objects.select_for_update()
            .filter(
                team_id=team_id,
                deleted=False,
                alert_destination_id__in=alert_destination_ids,
            )
            .values_list("id", flat=True)
        )
        deleted_count = HogFunction.objects.filter(team_id=team_id, id__in=owned_ids).update(
            deleted=True, enabled=False
        )
        _reload_hog_functions_after_commit(team_id=team_id, hog_function_ids=owned_ids)
        return deleted_count


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
