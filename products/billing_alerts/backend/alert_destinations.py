from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from posthog.models import Team

from products.billing_alerts.backend.models import BillingAlertConfiguration

EventKind = Literal["firing", "resolved", "errored", "broken"]
DestinationType = Literal["slack", "webhook", "teams"]

BILLING_ALERT_DESTINATION_IDS_PROPERTY = "billing_alert_destination_ids"

TEMPLATE_ID_BY_DESTINATION_TYPE: dict[DestinationType, str] = {
    "slack": "template-slack",
    "webhook": "template-webhook",
    "teams": "template-microsoft-teams",
}
DESTINATION_TYPE_BY_TEMPLATE_ID = {
    template_id: destination_type for destination_type, template_id in TEMPLATE_ID_BY_DESTINATION_TYPE.items()
}


@dataclass(frozen=True)
class EventKindSpec:
    event_id: str
    display_kind: str
    header: str
    details: tuple[tuple[str, str], ...]
    button_url: str
    button_label: str
    webhook_body: dict[str, Any]

    def destination_description(self, alert_name: str) -> str:
        return f'Sends {self.display_kind} notifications for billing alert "{alert_name}".'


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
    ),
}

EVENT_KINDS: tuple[EventKind, ...] = tuple(EVENT_KIND_CONFIG.keys())

_HOG_FUNCTION_NAME_MAX_LEN = 400


def _clip_name(name: str) -> str:
    if len(name) <= _HOG_FUNCTION_NAME_MAX_LEN:
        return name
    return name[: _HOG_FUNCTION_NAME_MAX_LEN - 3] + "..."


def _filter_for(alert: BillingAlertConfiguration, kind: EventKind) -> dict[str, Any]:
    return {
        "events": [{"id": EVENT_KIND_CONFIG[kind].event_id, "type": "events"}],
        "properties": [
            {
                "key": "alert_id",
                "value": str(alert.id),
                "operator": "exact",
                "type": "event",
            }
        ],
    }


def _slack_body(spec: EventKindSpec) -> str:
    return "\n".join(f"*{label}:* {value}" for label, value in spec.details)


def _slack_blocks(spec: EventKindSpec) -> list[dict]:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": spec.header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _slack_body(spec)}},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Organization billing alert"},
                {"type": "mrkdwn", "text": "Project: <{project.url}|{project.name}>"},
            ],
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "url": spec.button_url,
                    "text": {"text": spec.button_label, "type": "plain_text"},
                    "type": "button",
                }
            ],
        },
    ]


def _teams_text(spec: EventKindSpec) -> str:
    details = "\n\n".join(f"**{label}:** {value}" for label, value in spec.details)
    return f"**{spec.header}**\n\n{details}\n\n[{spec.button_label}]({spec.button_url})"


def _hog_function_config(
    alert: BillingAlertConfiguration,
    team: Team,
    kind: EventKind,
    *,
    template_id: str,
    name_suffix: str,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    spec = EVENT_KIND_CONFIG[kind]
    return {
        "team": team,
        "type": "internal_destination",
        "enabled": True,
        "filters": _filter_for(alert, kind),
        "name": _clip_name(f"Billing alert - {alert.name} ({spec.display_kind}) -> {name_suffix}"),
        "description": spec.destination_description(alert.name),
        "template_id": template_id,
        "inputs": inputs,
    }


def build_destination_config(
    alert: BillingAlertConfiguration,
    team: Team,
    kind: EventKind,
    data: dict[str, Any],
) -> dict[str, Any]:
    spec = EVENT_KIND_CONFIG[kind]
    if data["type"] == "slack":
        channel_display = data.get("slack_channel_name") or "channel"
        return _hog_function_config(
            alert,
            team,
            kind,
            template_id=TEMPLATE_ID_BY_DESTINATION_TYPE["slack"],
            name_suffix=f"Slack #{channel_display}",
            inputs={
                "blocks": {"value": _slack_blocks(spec)},
                "text": {"value": spec.header},
                "slack_workspace": {"value": data["slack_workspace_id"]},
                "channel": {"value": data["slack_channel_id"]},
            },
        )
    if data["type"] == "teams":
        return _hog_function_config(
            alert,
            team,
            kind,
            template_id=TEMPLATE_ID_BY_DESTINATION_TYPE["teams"],
            name_suffix="Microsoft Teams",
            inputs={
                "webhookUrl": {"value": data["webhook_url"]},
                "text": {"value": _teams_text(spec)},
            },
        )
    return _hog_function_config(
        alert,
        team,
        kind,
        template_id=TEMPLATE_ID_BY_DESTINATION_TYPE["webhook"],
        name_suffix=f"Webhook {data['webhook_url']}",
        inputs={
            "body": {"value": spec.webhook_body},
            "url": {"value": data["webhook_url"]},
            "headers": {"value": {"Content-Type": "application/json", "X-PostHog-Webhook-Version": "1"}},
        },
    )
