from __future__ import annotations

from typing import Any, Literal

from posthog.models import Team

from products.billing_alerts.backend.models import BillingAlertConfiguration

from common.alerting.destinations import (
    DESTINATION_TYPE_BY_TEMPLATE_ID,
    TEMPLATE_ID_BY_DESTINATION_TYPE,
    EventKindSpec,
    build_slack_destination_config,
    build_teams_destination_config,
    build_webhook_destination_config,
)

EventKind = Literal["firing", "resolved", "errored", "broken"]
DestinationType = Literal["slack", "webhook", "teams"]

BILLING_ALERT_DESTINATION_IDS_PROPERTY = "billing_alert_destination_ids"

__all__ = [
    "BILLING_ALERT_DESTINATION_IDS_PROPERTY",
    "DESTINATION_TYPE_BY_TEMPLATE_ID",
    "EVENT_KINDS",
    "EVENT_KIND_CONFIG",
    "TEMPLATE_ID_BY_DESTINATION_TYPE",
    "DestinationType",
    "EventKind",
    "build_destination_config",
]

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
        button_url="{project.url}/organization/billing/alerts",
        button_label="View billing alert",
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
        button_url="{project.url}/organization/billing/alerts",
        button_label="View billing alert",
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
        button_url="{project.url}/organization/billing/alerts",
        button_label="View billing alert",
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
        button_url="{project.url}/organization/billing/alerts",
        button_label="View billing alert",
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

EVENT_KINDS: tuple[EventKind, ...] = tuple(EVENT_KIND_CONFIG.keys())

_SLACK_CONTEXT_ELEMENTS = (
    "Organization billing alert",
    "Project: <{project.url}|{project.name}>",
)


def build_destination_config(
    alert: BillingAlertConfiguration,
    team: Team,
    kind: EventKind,
    data: dict[str, Any],
) -> dict[str, Any]:
    spec = EVENT_KIND_CONFIG[kind]
    alert_id = str(alert.id)
    if data["type"] == "slack":
        channel_display = data.get("slack_channel_name") or "channel"
        return build_slack_destination_config(
            team=team,
            spec=spec,
            alert_id=alert_id,
            alert_name=alert.name,
            name=f"Billing alert - {alert.name} ({spec.display_kind}) -> Slack #{channel_display}",
            slack_workspace_id=data["slack_workspace_id"],
            slack_channel_id=data["slack_channel_id"],
            context_elements=_SLACK_CONTEXT_ELEMENTS,
        )
    if data["type"] == "teams":
        return build_teams_destination_config(
            team=team,
            spec=spec,
            alert_id=alert_id,
            alert_name=alert.name,
            name=f"Billing alert - {alert.name} ({spec.display_kind}) -> Microsoft Teams",
            webhook_url=data["webhook_url"],
        )
    return build_webhook_destination_config(
        team=team,
        spec=spec,
        alert_id=alert_id,
        alert_name=alert.name,
        name=f"Billing alert - {alert.name} ({spec.display_kind}) -> Webhook {data['webhook_url']}",
        webhook_url=data["webhook_url"],
    )
