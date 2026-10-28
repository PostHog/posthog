"""Slack destinations for insight alerts.

The alert UI builds these from the `insight-alert-firing` Slack sub-template in
frontend/src/scenes/hog-functions/sub-templates/sub-templates.ts. The blocks here mirror that
entry, so a destination attached through the API posts the same message as one attached in the
UI — same chart, same buttons, same snooze menu. Keep the two in step.
"""

from __future__ import annotations

from typing import Any, Final

from products.alerts.backend.logic.destination_configs import (
    DESTINATION_SPECS,
    clip_hog_function_name,
    destination_filter,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationConfig,
    AlertDestinationData,
    DestinationType,
)
from products.cdp.backend.internal_events import LEGACY_INSIGHT_ALERT_EVENT

SLACK_TEMPLATE_ID: Final = DESTINATION_SPECS[DestinationType.SLACK].template_id

# A hog template that is a single {…} expression resolves to the expression's raw value, so this
# string becomes a whole block: a chart of the alerted insight when the anomaly investigation
# rendered one (`insight_chart_url` set by investigate_anomaly_activity), otherwise the plain
# divider — Slack has no way to omit a block conditionally, and an image block with an empty URL
# fails the send.
INSIGHT_CHART_BLOCK: Final = "{event.properties.insight_chart_url ? {'type': 'image', 'image_url': event.properties.insight_chart_url, 'alt_text': 'Insight chart'} : {'type': 'divider'}}"

# Points to the anomaly investigation notebook when present, otherwise falls back to the alert
# page (Slack can't conditionally hide a button, so the one button does double duty).
_PRIMARY_BUTTON_URL: Final = (
    "{event.properties.investigation_notebook_url ? event.properties.investigation_notebook_url : "
    "concat(project.url, '/insights/', event.properties.insight_id, '/alerts?alert_id=', "
    "event.properties.alert_id, '&utm_source=alert&utm_campaign=alert_check_firing&utm_medium=slack')}"
)

_SNOOZE_OPTIONS: Final = (
    ("For 1 hour", "1h"),
    ("For 6 hours", "6h"),
    ("For 1 day", "1d"),
    ("For 1 week", "1w"),
    ("Pick a date & time…", "custom"),
)


def snooze_select(alert_id: str) -> dict[str, Any]:
    """The snooze menu of an insight alert's Slack message, which the Slack app's snooze handler reads.

    The stock template passes a Hog placeholder for the id, and a native message passes the id itself.
    """
    return {
        "action_id": "insight_alert_snooze",
        "placeholder": {"text": "Snooze…", "type": "plain_text"},
        "options": [
            {"text": {"text": label, "type": "plain_text"}, "value": f"{alert_id}|{duration}"}
            for label, duration in _SNOOZE_OPTIONS
        ],
        "type": "static_select",
    }


def _slack_blocks(
    *,
    chart: Any = INSIGHT_CHART_BLOCK,
    alert_id: str = "{event.properties.alert_id}",
    primary_url: str = _PRIMARY_BUTTON_URL,
    primary_label: str = "{event.properties.investigation_notebook_url ? '🔎 View investigation' : '🔎 View alert'}",
    insight_url: str = "{project.url}/insights/{event.properties.insight_id}?utm_source=alert&utm_campaign=alert_check_firing&utm_medium=slack",
) -> list[Any]:
    return [
        chart,
        {
            "type": "actions",
            # A datetimepicker element carries no value, unlike a select option, so the alert id
            # in the block_id is the only way the snooze action can identify its alert.
            "block_id": f"insight_alert_snooze:{alert_id}",
            "elements": [
                {
                    "url": primary_url,
                    "text": {
                        "text": primary_label,
                        "type": "plain_text",
                    },
                    "type": "button",
                },
                {
                    "url": insight_url,
                    "text": {"text": "📊 View insight", "type": "plain_text"},
                    "type": "button",
                },
                snooze_select(alert_id),
            ],
        },
    ]


def _slack_attachments(
    *,
    heading_prefix: str = "{concat('⚠️ ', event.properties.slack_alert_type == 'Anomaly detected' ? 'Anomaly alert' : 'Insight alert', ' ‘')}",
    alert_name: str = "{event.properties.alert_name}",
    alert_url: str = "{project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id}",
    project_name: str = "{project.name}",
    project_url: str = "{project.url}",
    details: Any = "{event.properties.slack_alert_details ?? {'type': 'section', 'text': {'type': 'plain_text', 'text': substring(event.properties.breaches, 1, 3000)}}}",
    timing: Any = "{event.properties.slack_alert_timing ?? {'type': 'context', 'elements': [{'type': 'plain_text', 'text': event.timestamp}]}}",
    tags: Any = "{event.properties.slack_alert_tags ?? {'type': 'divider'}}",
    fallback: str = "{concat(event.properties.slack_alert_type == 'Anomaly detected' ? 'Anomaly alert' : 'Insight alert', ' ‘', event.properties.alert_name, '’ triggered')}",
    blocks: list[Any] | None = None,
) -> list[Any]:
    return [
        {
            "color": "#D97706",
            "fallback": fallback,
            "blocks": [
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [
                                {
                                    "type": "text",
                                    "text": heading_prefix,
                                    "style": {"bold": True},
                                },
                                {
                                    "type": "link",
                                    "url": alert_url,
                                    "text": alert_name,
                                    "style": {"bold": True},
                                },
                                {"type": "text", "text": "’ triggered", "style": {"bold": True}},
                            ],
                        }
                    ],
                },
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [
                                {"type": "text", "text": "📁 Project: "},
                                {"type": "link", "url": project_url, "text": project_name},
                            ],
                        }
                    ],
                },
                details,
                timing,
                tags,
            ],
        },
        {"blocks": _slack_blocks() if blocks is None else blocks},
    ]


def build_insight_alert_slack_config(
    *, alert_id: str, alert_name: str | None, data: AlertDestinationData
) -> AlertDestinationConfig:
    channel_name = data.get("slack_channel_name") or "channel"
    return AlertDestinationConfig(
        payload={
            "type": "internal_destination",
            "enabled": True,
            "filters": destination_filter(alert_id, LEGACY_INSIGHT_ALERT_EVENT),
            "name": clip_hog_function_name(f"{alert_name or 'Alert'}: Slack #{channel_name}"),
            "template_id": SLACK_TEMPLATE_ID,
            "inputs": {
                "blocks": {"value": []},
                "attachments": {"value": _slack_attachments()},
                "text": {"value": ""},
                "slack_workspace": {"value": data["slack_workspace_id"]},
                "channel": {"value": data["slack_channel_id"]},
            },
        },
    )
