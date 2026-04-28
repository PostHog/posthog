"""Build HogFunction configurations for insight alert notifications.

Mirrors the logs alerts destination builder (`products/logs/backend/alert_destinations.py`).
Insight alerts only emit a single internal event (`$insight_alert_firing`), so unlike logs
alerts there's only one HogFunction per destination instead of one per event kind.
"""

from __future__ import annotations

from typing import Any

from posthog.models.alert import AlertConfiguration

INSIGHT_ALERT_FIRING_EVENT_ID = "$insight_alert_firing"

_SLACK_BLOCKS: list[dict[str, Any]] = [
    {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Alert '{event.properties.alert_name}' firing for insight '{event.properties.insight_name}'",
        },
    },
    {
        "type": "section",
        "text": {"type": "plain_text", "text": "{event.properties.breaches}"},
    },
    {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "Project: <{project.url}|{project.name}>"}],
    },
    {"type": "divider"},
    {
        "type": "actions",
        "elements": [
            {
                "url": "{project.url}/insights/{event.properties.insight_id}",
                "text": {"text": "View Insight", "type": "plain_text"},
                "type": "button",
            },
            {
                "url": "{project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id}",
                "text": {"text": "View Alert", "type": "plain_text"},
                "type": "button",
            },
        ],
    },
]

_WEBHOOK_BODY: dict[str, str] = {
    "alert_name": "{event.properties.alert_name}",
    "insight_name": "{event.properties.insight_name}",
    "breaches": "{event.properties.breaches}",
    "insight_url": "{project.url}/insights/{event.properties.insight_id}",
    "alert_url": "{project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id}",
}


def _filter_for(alert: AlertConfiguration) -> dict[str, Any]:
    return {
        "events": [{"id": INSIGHT_ALERT_FIRING_EVENT_ID, "type": "events"}],
        "properties": [
            {
                "key": "alert_id",
                "value": str(alert.id),
                "operator": "exact",
                "type": "event",
            }
        ],
    }


def _alert_display_name(alert: AlertConfiguration) -> str:
    return alert.name or f"Alert for {alert.insight.name or 'insight'}"


def build_slack_config(
    alert: AlertConfiguration,
    slack_workspace_id: int,
    slack_channel_id: str,
    slack_channel_name: str | None,
) -> dict[str, Any]:
    channel_display = slack_channel_name or "channel"
    return {
        "team": alert.team,
        "type": "internal_destination",
        "enabled": True,
        "filters": _filter_for(alert),
        "name": f"{_alert_display_name(alert)}: Slack #{channel_display}",
        "template_id": "template-slack",
        "inputs": {
            "blocks": {"value": _SLACK_BLOCKS},
            "text": {"value": "Alert triggered: {event.properties.insight_name}"},
            "slack_workspace": {"value": slack_workspace_id},
            "channel": {"value": slack_channel_id},
        },
    }


def build_webhook_config(alert: AlertConfiguration, webhook_url: str) -> dict[str, Any]:
    return {
        "team": alert.team,
        "type": "internal_destination",
        "enabled": True,
        "filters": _filter_for(alert),
        "name": f"{_alert_display_name(alert)}: Webhook {webhook_url}",
        "template_id": "template-webhook",
        "inputs": {
            "url": {"value": webhook_url},
            "body": {"value": _WEBHOOK_BODY},
        },
    }
