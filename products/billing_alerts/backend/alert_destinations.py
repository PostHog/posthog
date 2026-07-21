from __future__ import annotations

from typing import Final, Literal

from django.db.models import Q

from products.alerts.backend.destination_configs import DestinationType, EventKindSpec
from products.alerts.backend.facade.api import DESTINATION_TEMPLATE_IDS
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

EventKind = Literal["firing", "resolved", "errored", "broken"]

BILLING_DESTINATION_TYPES = (DestinationType.SLACK, DestinationType.WEBHOOK, DestinationType.TEAMS)

DESTINATION_TYPE_BY_TEMPLATE_ID = {
    DESTINATION_TEMPLATE_IDS[destination_type]: destination_type for destination_type in BILLING_DESTINATION_TYPES
}

_PRODUCT_LABEL = "billing alert"
_BASE_DATA = {
    "alert_id": "{event.properties.alert_id}",
    "alert_name": "{event.properties.alert_name}",
    "metric": "{event.properties.metric}",
    "current_value": "{event.properties.current_value}",
    "baseline_value": "{event.properties.baseline_value}",
    "absolute_delta": "{event.properties.absolute_delta}",
    "relative_delta_percentage": "{event.properties.relative_delta_percentage}",
    "evaluation_date": "{event.properties.evaluation_date}",
    "reason": "{event.properties.reason}",
    "alert_url": "{project.url}/organization/billing",
}


_ERROR_DATA = {
    "error_message": "{event.properties.error_message}",
    "consecutive_failures": "{event.properties.consecutive_failures}",
}


def _spec(
    *,
    event: str,
    display_kind: str,
    header: str,
    details: tuple[tuple[str, str], ...],
    extra_data: dict[str, str] | None = None,
) -> EventKindSpec:
    return EventKindSpec(
        event_id=f"$billing_alert_{event}",
        display_kind=display_kind,
        header=header,
        details=details,
        primary_action_url="{project.url}/organization/billing",
        primary_action_label="View billing alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": f"billing_alert.{event}",
            "timestamp": "{event.properties.triggered_at}",
            "data": {**_BASE_DATA, **(extra_data or {})},
        },
        product_label=_PRODUCT_LABEL,
    )


EVENT_KIND_CONFIG: dict[EventKind, EventKindSpec] = {
    "firing": _spec(
        event="firing",
        display_kind="firing",
        header="Billing alert '{event.properties.alert_name}' is firing",
        details=(
            ("Metric", "{event.properties.metric}"),
            ("Current", "{event.properties.current_value}"),
            ("Baseline", "{event.properties.baseline_value}"),
            ("Reason", "{event.properties.reason}"),
        ),
    ),
    "resolved": _spec(
        event="resolved",
        display_kind="resolved",
        header="Billing alert '{event.properties.alert_name}' has resolved",
        details=(
            ("Metric", "{event.properties.metric}"),
            ("Current", "{event.properties.current_value}"),
            ("Baseline", "{event.properties.baseline_value}"),
            ("Reason", "{event.properties.reason}"),
        ),
    ),
    "errored": _spec(
        event="errored",
        display_kind="errored",
        header="Billing alert '{event.properties.alert_name}' could not evaluate",
        details=(
            ("Error", "{event.properties.error_message}"),
            ("Failure count", "{event.properties.consecutive_failures}"),
        ),
        extra_data=_ERROR_DATA,
    ),
    "broken": _spec(
        event="auto_disabled",
        display_kind="auto-disabled",
        header="Billing alert '{event.properties.alert_name}' was auto-disabled",
        details=(
            ("Reason", "{event.properties.consecutive_failures} consecutive check failures."),
            ("Last error", "{event.properties.error_message}"),
        ),
        extra_data=_ERROR_DATA,
    ),
}

EVENT_KINDS: tuple[EventKind, ...] = tuple(EVENT_KIND_CONFIG)
BILLING_ALERT_EVENT_IDS: Final = tuple(spec.event_id for spec in EVENT_KIND_CONFIG.values())

BILLING_ALERT_SLACK_CONTEXT_ELEMENTS = (
    "Organization-wide billing alert",
    "Execution project: <{project.url}|{project.name}>",
)


def destination_groups_for_alerts(
    *,
    team_ids: set[int],
    alert_ids: set[str],
) -> dict[str, dict[str, dict[str, str]]]:
    """Map alert id -> destination type value -> event id -> HogFunction id for enabled,
    billing-owned destinations.

    This is the single implementation of destination-group resolution; callers enforce the
    complete-group invariant (a group must cover every event kind) on the returned mapping.
    """
    if not team_ids or not alert_ids:
        return {}

    ownership_filter = Q(pk__in=[])
    for alert_id in alert_ids:
        ownership_filter |= Q(filters__properties__contains=[{"key": "alert_id", "value": alert_id}])

    rows = HogFunction.objects.filter(
        ownership_filter,
        team_id__in=team_ids,
        enabled=True,
        deleted=False,
        template_id__in=list(DESTINATION_TYPE_BY_TEMPLATE_ID),
    ).values_list("id", "template_id", "filters")

    groups: dict[str, dict[str, dict[str, str]]] = {}
    for hog_function_id, template_id, filters in rows:
        destination_type = DESTINATION_TYPE_BY_TEMPLATE_ID.get(template_id) if template_id else None
        if destination_type is None or not isinstance(filters, dict):
            continue
        properties = filters.get("properties") or []
        events = filters.get("events") or []
        if not isinstance(properties, list) or not isinstance(events, list):
            continue
        event_id = next(
            (
                event_filter.get("id")
                for event_filter in events
                if isinstance(event_filter, dict) and event_filter.get("type") == "events"
            ),
            None,
        )
        if event_id not in BILLING_ALERT_EVENT_IDS:
            continue
        for property_filter in properties:
            if not isinstance(property_filter, dict) or property_filter.get("key") != "alert_id":
                continue
            alert_id = str(property_filter.get("value"))
            if alert_id in alert_ids:
                groups.setdefault(alert_id, {}).setdefault(destination_type.value, {})[event_id] = str(hog_function_id)
            break
    return groups
