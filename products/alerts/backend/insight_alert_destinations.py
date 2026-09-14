"""Slack destinations for insight alerts.

The alert UI builds these from the `insight-alert-firing` Slack sub-template in
frontend/src/scenes/hog-functions/sub-templates/sub-templates.ts. The blocks here mirror that
entry, so a destination attached through the API posts the same message as one attached in the
UI — same chart, same buttons, same snooze menu. Keep the two in step.
"""

from __future__ import annotations

from typing import Any, Final

from posthog.cdp.internal_events import LEGACY_INSIGHT_ALERT_EVENT

from products.alerts.backend.destination_configs import (
    DESTINATION_SPECS,
    AlertDestinationConfig,
    AlertDestinationData,
    DestinationType,
    clip_hog_function_name,
    destination_filter,
)

# The event an insight alert check emits, named legacy where it is defined because it predates the
# managed-alert event boundary. Do not take it from `posthog.tasks.alerts.utils` instead, because
# that module imports this product's facade, which imports this one.
INSIGHT_ALERT_EVENT_IDS: Final[tuple[str, ...]] = (LEGACY_INSIGHT_ALERT_EVENT,)

# Slack only, because `alert:write` is grantable to a sandboxed agent. A connected workspace is a
# destination an admin chose, while every other transport takes a URL the caller supplies.
INSIGHT_ALERT_DESTINATION_TYPES: Final[tuple[DestinationType, ...]] = (DestinationType.SLACK,)

# Each destination is another message every time the alert fires, so a caller in a loop is capped.
MAX_DESTINATIONS_PER_ALERT: Final = 5

# One destination is one HogFunction, so this only stops a malformed request becoming a huge query.
MAX_DESTINATION_IDS_PER_DELETE_REQUEST: Final = 100

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


def _slack_blocks() -> list[Any]:
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Alert '{event.properties.alert_name}' firing for insight '{event.properties.insight_name}'",
            },
        },
        {
            # plain_text (not mrkdwn) so user-controlled names in the breach text can't inject
            # Slack markup/links/mentions. Newlines still render as line breaks.
            "type": "section",
            "text": {"type": "plain_text", "text": "{event.properties.breaches}"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "Project: <{project.url}|{project.name}>"}],
        },
        INSIGHT_CHART_BLOCK,
        {
            "type": "actions",
            # A datetimepicker element carries no value, unlike a select option, so the alert id
            # in the block_id is the only way the snooze action can identify its alert.
            "block_id": "insight_alert_snooze:{event.properties.alert_id}",
            "elements": [
                {
                    "url": _PRIMARY_BUTTON_URL,
                    "text": {
                        "text": "{event.properties.investigation_notebook_url ? 'View Investigation' : 'View Alert'}",
                        "type": "plain_text",
                    },
                    "type": "button",
                },
                {
                    "url": "{project.url}/insights/{event.properties.insight_id}?utm_source=alert&utm_campaign=alert_check_firing&utm_medium=slack",
                    "text": {"text": "View Insight", "type": "plain_text"},
                    "type": "button",
                },
                {
                    "action_id": "insight_alert_snooze",
                    "placeholder": {"text": "Snooze…", "type": "plain_text"},
                    "options": [
                        {
                            "text": {"text": label, "type": "plain_text"},
                            "value": "{event.properties.alert_id}|" + duration,
                        }
                        for label, duration in _SNOOZE_OPTIONS
                    ],
                    "type": "static_select",
                },
            ],
        },
    ]


def build_insight_alert_slack_config(
    *, team: Any, alert_id: str, alert_name: str | None, data: AlertDestinationData
) -> AlertDestinationConfig:
    channel_name = data.get("slack_channel_name") or "channel"
    return AlertDestinationConfig(
        team=team,
        payload={
            "type": "internal_destination",
            "enabled": True,
            "filters": destination_filter(alert_id, LEGACY_INSIGHT_ALERT_EVENT),
            "name": clip_hog_function_name(f"{alert_name or 'Alert'}: Slack #{channel_name}"),
            "template_id": SLACK_TEMPLATE_ID,
            "inputs": {
                "blocks": {"value": _slack_blocks()},
                "text": {"value": "Alert triggered: {event.properties.insight_name}"},
                "slack_workspace": {"value": data["slack_workspace_id"]},
                "channel": {"value": data["slack_channel_id"]},
            },
        },
    )
