"""Django persistence and dispatch for alert notification destinations."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, NamedTuple, cast
from urllib.parse import urlsplit
from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet

import structlog
import posthoganalytics
from prometheus_client import Counter
from rest_framework.exceptions import ValidationError

from posthog.cdp.internal_events import InternalEventEvent, flush_internal_events_producer, produce_internal_event
from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.client import ProduceResult
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers

from products.alerts.backend.destination_configs import (
    SPEC_BY_TEMPLATE_ID,
    AlertDestinationConfig,
    AlertDestinationData,
)
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


class AlertDestinationGroupKey(NamedTuple):
    template_id: str
    config: tuple[tuple[str, Any], ...] | None

    @property
    def is_config_readable(self) -> bool:
        return self.config is not None


class AlertDestinationRow(NamedTuple):
    hog_function_id: UUID
    template_id: str | None
    inputs: dict[str, Any] | None


@dataclass(frozen=True, kw_only=True)
class AlertDestinationGroup:
    hog_function_ids: tuple[UUID, ...]
    data: AlertDestinationData
    fully_enabled: bool


def alert_destination_group_key(*, template_id: str, inputs: dict[str, Any] | None) -> AlertDestinationGroupKey:
    spec = SPEC_BY_TEMPLATE_ID.get(template_id)
    if spec is None:
        return AlertDestinationGroupKey(template_id, None)
    data = spec.read(inputs or {})
    config = {key: value for key, value in data.items() if key != "type"}
    return AlertDestinationGroupKey(template_id, tuple(sorted(config.items())) if config else None)


def group_alert_destination_rows(rows: Collection[AlertDestinationRow]) -> dict[AlertDestinationGroupKey, set[UUID]]:
    keys_by_row = [
        (row.hog_function_id, alert_destination_group_key(template_id=row.template_id or "", inputs=row.inputs))
        for row in rows
    ]
    templates_with_an_unreadable_row = {key.template_id for _, key in keys_by_row if not key.is_config_readable}

    ids_by_group: dict[AlertDestinationGroupKey, set[UUID]] = {}
    for hog_function_id, key in keys_by_row:
        widened_key = (
            AlertDestinationGroupKey(key.template_id, None)
            if key.template_id in templates_with_an_unreadable_row
            else key
        )
        ids_by_group.setdefault(widened_key, set()).add(hog_function_id)
    return ids_by_group


def list_alert_destination_groups(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> list[AlertDestinationGroup]:
    raw_rows = list(
        owned_alert_destinations_qs(team_id=team_id, alert_ids=[alert_id], allowed_event_ids=allowed_event_ids)
        .order_by("created_at", "id")
        .values_list("id", "template_id", "inputs", "enabled")
    )
    rows = [AlertDestinationRow(row_id, template_id, inputs) for row_id, template_id, inputs, _ in raw_rows]
    grouped_ids = group_alert_destination_rows(rows)
    enabled_by_id = {row_id: enabled for row_id, _, _, enabled in raw_rows}

    groups: list[AlertDestinationGroup] = []
    for key, ids in grouped_ids.items():
        spec = SPEC_BY_TEMPLATE_ID.get(key.template_id)
        if spec is None:
            continue
        data = cast(AlertDestinationData, {"type": spec.type, **dict(key.config or ())})
        groups.append(
            AlertDestinationGroup(
                hog_function_ids=tuple(sorted(ids)),
                data=data,
                fully_enabled=all(enabled_by_id[hog_function_id] for hog_function_id in ids),
            )
        )
    return groups


def owned_alert_destinations_qs(
    *, team_id: int, alert_ids: Collection[str], allowed_event_ids: Collection[str]
) -> QuerySet[HogFunction]:
    alert_id_filter = Q(pk__in=[])
    for alert_id in alert_ids:
        alert_id_filter |= Q(filters__properties__contains=[{"key": "alert_id", "value": alert_id}])
    return HogFunction.objects.filter(
        alert_id_filter,
        _allowed_event_filter(allowed_event_ids),
        team_id=team_id,
        deleted=False,
        template_id__in=SPEC_BY_TEMPLATE_ID,
    )


def _active_alert_destinations_qs(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> QuerySet[HogFunction]:
    return owned_alert_destinations_qs(
        team_id=team_id, alert_ids=[alert_id], allowed_event_ids=allowed_event_ids
    ).filter(enabled=True)


def _raise_if_alert_already_has_these_destination_configs(
    *,
    team_id: int,
    alert_id: str,
    allowed_event_ids: Collection[str],
    configs: Collection[AlertDestinationConfig],
) -> None:
    wanted_keys = {
        alert_destination_group_key(template_id=config.payload["template_id"], inputs=config.payload["inputs"])
        for config in configs
    }
    # An unreadable config can't be compared, so it can't be proven a duplicate.
    readable_keys = {key for key in wanted_keys if key.is_config_readable}
    if not readable_keys:
        return
    stored_rows = (
        owned_alert_destinations_qs(team_id=team_id, alert_ids=[alert_id], allowed_event_ids=allowed_event_ids)
        .filter(template_id__in={key.template_id for key in readable_keys})
        .values_list("template_id", "inputs")
    )
    if any(
        alert_destination_group_key(template_id=template_id or "", inputs=inputs) in readable_keys
        for template_id, inputs in stored_rows
    ):
        raise ValidationError("This destination is already configured for this alert.")


def create_alert_destination_hog_functions(
    configs: list[AlertDestinationConfig], *, request: Any, alert_id: str, allowed_event_ids: Collection[str]
) -> list[HogFunction]:
    if not configs:
        return []
    created: list[HogFunction] = []
    hog_function_ids_by_team: dict[int, list[UUID]] = {}
    with transaction.atomic():
        _raise_if_alert_already_has_these_destination_configs(
            team_id=configs[0].team.id,
            alert_id=alert_id,
            allowed_event_ids=allowed_event_ids,
            configs=configs,
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
            created.append(hog_function)
            hog_function_ids_by_team.setdefault(team.id, []).append(hog_function.id)
        for team_id, hog_function_ids in hog_function_ids_by_team.items():
            _reload_hog_functions_after_commit(team_id=team_id, hog_function_ids=hog_function_ids)
    return created


def _report_unreadable_destination_configs(
    *, team_id: int, alert_id: str, rows: Collection[AlertDestinationRow]
) -> None:
    row_counts_by_template: dict[str, int] = {}
    for row in rows:
        template_id = row.template_id or ""
        if not alert_destination_group_key(template_id=template_id, inputs=row.inputs).is_config_readable:
            row_counts_by_template[template_id] = row_counts_by_template.get(template_id, 0) + 1
    for template_id, count in row_counts_by_template.items():
        posthoganalytics.capture(
            distinct_id=f"team_{team_id}",
            event="alert destination config unreadable",
            properties={
                "alert_id": alert_id,
                "feature": "alerts",
                "row_count": count,
                "team_id": team_id,
                "template_id": template_id,
            },
        )
    if row_counts_by_template:
        logger.warning(
            "Alert destination config could not be read",
            alert_id=alert_id,
            feature="alerts",
            row_counts_by_template=row_counts_by_template,
            team_id=team_id,
        )


def soft_delete_alert_destinations(
    *,
    team_id: int,
    alert_id: str,
    allowed_event_ids: Collection[str],
    hog_function_ids: list[UUID],
) -> None:
    unique_ids = set(hog_function_ids)
    with transaction.atomic():
        owned_rows = [
            AlertDestinationRow(*row)
            for row in owned_alert_destinations_qs(
                team_id=team_id, alert_ids=[alert_id], allowed_event_ids=allowed_event_ids
            )
            .select_for_update()
            .values_list("id", "template_id", "inputs")
        ]
        owned_ids = {row.hog_function_id for row in owned_rows}
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

        _report_unreadable_destination_configs(team_id=team_id, alert_id=alert_id, rows=owned_rows)

        for group_key, group_ids in group_alert_destination_rows(owned_rows).items():
            names_only_part_of_the_group = bool(group_ids & unique_ids) and not group_ids <= unique_ids
            if names_only_part_of_the_group:
                message = (
                    "Delete all destinations in this group together."
                    if group_key.is_config_readable
                    else "Some destinations of this type have settings that can no longer be read. To delete any of them, remove every destination of this type together."
                )
                raise ValidationError({"hog_function_ids": [message]})

        HogFunction.objects.filter(team_id=team_id, id__in=unique_ids).update(deleted=True, enabled=False)
        _reload_hog_functions_after_commit(team_id=team_id, hog_function_ids=unique_ids)


def soft_delete_all_alert_destinations(*, team_id: int, alert_id: str, allowed_event_ids: Collection[str]) -> int:
    return soft_delete_alert_destinations_for_alerts(
        team_id=team_id, alert_ids=[alert_id], allowed_event_ids=allowed_event_ids
    )


def soft_delete_alert_destinations_for_alerts(
    *, team_id: int, alert_ids: Collection[str], allowed_event_ids: Collection[str]
) -> int:
    """Soft-delete alert-owned destinations in bulk."""
    with transaction.atomic():
        destination_ids = set(
            owned_alert_destinations_qs(team_id=team_id, alert_ids=alert_ids, allowed_event_ids=allowed_event_ids)
            .select_for_update()
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
        spec = SPEC_BY_TEMPLATE_ID.get(template_id) if template_id else None
        destinations.append(
            ActiveAlertDestination(
                id=str(hog_function_id),
                name=_destination_display_name(name) if name else "Destination",
                destination_type=spec.type.value if spec else None,
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
