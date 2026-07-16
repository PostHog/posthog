from __future__ import annotations

from typing import Final, Literal

from products.alerts.backend.destination_configs import DestinationType, EventKindSpec
from products.alerts.backend.facade.api import DESTINATION_TEMPLATE_IDS

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
    "alert_url": "{project.url}/organization/billing/alerts",
}


EVENT_KIND_CONFIG: dict[EventKind, EventKindSpec] = {
    "firing": EventKindSpec(
        event_id="$billing_alert_firing",
        display_kind="firing",
        header="Billing alert '{event.properties.alert_name}' is firing",
        details=(
            ("Metric", "{event.properties.metric}"),
            ("Current", "{event.properties.current_value}"),
            ("Baseline", "{event.properties.baseline_value}"),
            ("Reason", "{event.properties.reason}"),
        ),
        primary_action_url="{project.url}/organization/billing/alerts",
        primary_action_label="View billing alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "billing_alert.firing",
            "timestamp": "{event.properties.triggered_at}",
            "data": _BASE_DATA,
        },
        product_label=_PRODUCT_LABEL,
    ),
    "resolved": EventKindSpec(
        event_id="$billing_alert_resolved",
        display_kind="resolved",
        header="Billing alert '{event.properties.alert_name}' has resolved",
        details=(
            ("Metric", "{event.properties.metric}"),
            ("Current", "{event.properties.current_value}"),
            ("Baseline", "{event.properties.baseline_value}"),
            ("Reason", "{event.properties.reason}"),
        ),
        primary_action_url="{project.url}/organization/billing/alerts",
        primary_action_label="View billing alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "billing_alert.resolved",
            "timestamp": "{event.properties.triggered_at}",
            "data": _BASE_DATA,
        },
        product_label=_PRODUCT_LABEL,
    ),
    "errored": EventKindSpec(
        event_id="$billing_alert_errored",
        display_kind="errored",
        header="Billing alert '{event.properties.alert_name}' could not evaluate",
        details=(
            ("Error", "{event.properties.error_message}"),
            ("Failure count", "{event.properties.consecutive_failures}"),
        ),
        primary_action_url="{project.url}/organization/billing/alerts",
        primary_action_label="View billing alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "billing_alert.errored",
            "timestamp": "{event.properties.triggered_at}",
            "data": {
                **_BASE_DATA,
                "error_message": "{event.properties.error_message}",
                "consecutive_failures": "{event.properties.consecutive_failures}",
            },
        },
        product_label=_PRODUCT_LABEL,
    ),
    "broken": EventKindSpec(
        event_id="$billing_alert_auto_disabled",
        display_kind="auto-disabled",
        header="Billing alert '{event.properties.alert_name}' was auto-disabled",
        details=(
            ("Reason", "{event.properties.consecutive_failures} consecutive check failures."),
            ("Last error", "{event.properties.error_message}"),
        ),
        primary_action_url="{project.url}/organization/billing/alerts",
        primary_action_label="View billing alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "billing_alert.auto_disabled",
            "timestamp": "{event.properties.triggered_at}",
            "data": {
                **_BASE_DATA,
                "error_message": "{event.properties.error_message}",
                "consecutive_failures": "{event.properties.consecutive_failures}",
            },
        },
        product_label=_PRODUCT_LABEL,
    ),
}

EVENT_KINDS: tuple[EventKind, ...] = tuple(EVENT_KIND_CONFIG)
BILLING_ALERT_EVENT_IDS: Final = tuple(spec.event_id for spec in EVENT_KIND_CONFIG.values())

BILLING_ALERT_SLACK_CONTEXT_ELEMENTS = (
    "Organization billing alert",
    "Project: <{project.url}|{project.name}>",
)
