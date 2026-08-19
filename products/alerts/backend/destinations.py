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

from products.alerts.backend.destination_configs import (
    DESTINATION_TEMPLATE_IDS,
    AlertDestinationConfig,
    DestinationType,
    read_alert_destination_data,
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

ALERT_DESTINATION_UNREADABLE_CONFIGS = Counter(
    "posthog_alert_destination_unreadable_configs_total",
    "Live alert destination HogFunctions whose config could not be read while grouping a delete",
    labelnames=["template_id"],
)

# Not one destination's worth of rows: an alert that already has duplicate destinations holds them
# in a single delete group, which comes out only when every row of it is named.
# soft_delete_alert_destinations enforces the real rule, so this is a request-size bound only.
ALERT_DESTINATION_DELETE_MAX_IDS = 100


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


AlertDestinationGroupKey = tuple[str, tuple[tuple[str, Any], ...]]


# Config half of the group key for rows whose config could not be read. No readable config
# produces this pair, so it never collides with a real destination.
UNREADABLE_DESTINATION_CONFIG: tuple[tuple[str, Any], ...] = (("config", "unreadable"),)


def alert_destination_config_key(
    *, template_id: str | None, inputs: dict[str, Any] | None
) -> AlertDestinationGroupKey | None:
    """Identify the destination one HogFunction belongs to, or None if its config cannot be read.

    Creating a destination fans out into one HogFunction per event kind, so the rows of a single
    destination are the ones sharing a template and the config written into their inputs (the
    Slack channel, the webhook URL). Two Slack channels on one alert are therefore two groups.
    """
    if not template_id:
        return None
    destination_type_value = _TEMPLATE_ID_TO_DESTINATION_TYPE.get(template_id)
    if destination_type_value is None:
        return None
    data = read_alert_destination_data(destination_type=DestinationType(destination_type_value), inputs=inputs or {})
    config = {key: value for key, value in data.items() if key != "type"}
    if not config:
        return None
    return (template_id, tuple(sorted(config.items())))


def _owned_alert_destinations_qs(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> QuerySet[HogFunction]:
    """Every not-yet-deleted destination row this alert owns, disabled ones included.

    Deletes and the duplicate check both work on this set. A disabled row still belongs to its
    destination group, so leaving it out would let a delete split the group.
    """
    return HogFunction.objects.filter(
        _allowed_event_filter(allowed_event_ids),
        team_id=team_id,
        deleted=False,
        template_id__in=DESTINATION_TEMPLATE_IDS.values(),
        filters__properties__contains=[{"key": "alert_id", "value": alert_id}],
    )


def _active_alert_destinations_qs(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> QuerySet[HogFunction]:
    return _owned_alert_destinations_qs(team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids).filter(
        enabled=True
    )


def raise_if_alert_destination_exists(
    *,
    team_id: int,
    alert_id: str,
    allowed_event_ids: Collection[str],
    template_id: str,
    inputs: dict[str, Any],
) -> None:
    """Refuse a second destination with the same config on one alert.

    A duplicate sends every notification twice, and its rows join the original's delete group, so
    afterwards the two can only be removed together.
    """
    config_key = alert_destination_config_key(template_id=template_id, inputs=inputs)
    if config_key is None:
        return
    existing_keys = {
        alert_destination_config_key(template_id=row_template_id, inputs=row_inputs)
        for row_template_id, row_inputs in _owned_alert_destinations_qs(
            team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids
        ).values_list("template_id", "inputs")
    }
    if config_key in existing_keys:
        raise ValidationError("This destination is already configured for this alert.")


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


def _report_unreadable_destination_configs(
    *, team_id: int, alert_id: str, keyed_rows: list[tuple[UUID, str, AlertDestinationGroupKey | None]]
) -> set[str]:
    """Record which templates have a row whose config could not be read, and return them.

    An unreadable config makes deletes coarser for its whole template without anything showing up
    in the response, so it needs a signal of its own. It happens when a template starts marking a
    config input secret, which moves that input out of `inputs`.
    """
    row_counts_by_template: dict[str, int] = {}
    for _, template_id, config_key in keyed_rows:
        if config_key is None:
            row_counts_by_template[template_id] = row_counts_by_template.get(template_id, 0) + 1
    for template_id, count in row_counts_by_template.items():
        ALERT_DESTINATION_UNREADABLE_CONFIGS.labels(template_id=template_id).inc(count)
    if row_counts_by_template:
        logger.warning(
            "Alert destination config could not be read",
            alert_id=alert_id,
            feature="alerts",
            row_counts_by_template=row_counts_by_template,
            team_id=team_id,
        )
    return set(row_counts_by_template)


def soft_delete_alert_destinations(
    *,
    team_id: int,
    alert_id: str,
    allowed_event_ids: Collection[str],
    hog_function_ids: list[UUID],
) -> None:
    unique_ids = set(hog_function_ids)
    with transaction.atomic():
        owned_rows = list(
            _owned_alert_destinations_qs(team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids)
            .select_for_update()
            .values_list("id", "template_id", "inputs")
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

        keyed_rows = [
            (hog_function_id, template_id or "", alert_destination_config_key(template_id=template_id, inputs=inputs))
            for hog_function_id, template_id, inputs in owned_rows
        ]
        unreadable_templates = _report_unreadable_destination_configs(
            team_id=team_id, alert_id=alert_id, keyed_rows=keyed_rows
        )

        ids_by_group: dict[AlertDestinationGroupKey, set[UUID]] = {}
        for hog_function_id, template_id, config_key in keyed_rows:
            # A row whose config cannot be read cannot be told apart from the other rows of its
            # template, so the whole template becomes one group. Grouping it alone instead would
            # let a caller delete part of a real destination and leave the rest sending.
            key = (
                (template_id, UNREADABLE_DESTINATION_CONFIG)
                if config_key is None or template_id in unreadable_templates
                else config_key
            )
            ids_by_group.setdefault(key, set()).add(hog_function_id)

        # A destination is deleted whole or not at all, so every live row of a group the request
        # touches has to be named. Whether the group covers all of allowed_event_ids is not
        # checked: a destination missing an event kind still has to be removable.
        for (_, config), group_ids in ids_by_group.items():
            if group_ids & unique_ids and not group_ids <= unique_ids:
                message = (
                    "Some destinations of this type can no longer be read, so every destination of this type has to be deleted together."
                    if config == UNREADABLE_DESTINATION_CONFIG
                    else "Delete every HogFunction in the destination group together."
                )
                raise ValidationError({"hog_function_ids": [message]})

        HogFunction.objects.filter(team_id=team_id, id__in=unique_ids).update(deleted=True, enabled=False)
        _reload_hog_functions_after_commit(team_id=team_id, hog_function_ids=unique_ids)


def soft_delete_all_alert_destinations(*, team_id: int, alert_id: str, allowed_event_ids: Collection[str]) -> int:
    with transaction.atomic():
        owned_ids = set(
            _owned_alert_destinations_qs(team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids)
            .select_for_update()
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
