"""Shared builders for alert notification destinations (CDP internal_destination HogFunctions).

Every alerting product delivers notifications the same way: an internal event per
alert-event kind (firing, resolved, errored, auto-disabled), consumed by one
HogFunction per destination per kind, linked to the alert via an `alert_id`
property filter. This module owns that wiring — the filter shape, the template
input structure per destination type, and the message scaffolding — so dispatch
and destinations can never drift apart per product.

Products own the content: their `EventKindSpec` table (event names, headers,
detail rows, payload data) and the display name of each HogFunction.

Pure Python — the `team` value is passed through opaquely into the config dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

DestinationType = Literal["slack", "webhook", "teams"]

ALERT_ID_PROPERTY = "alert_id"

TEMPLATE_ID_BY_DESTINATION_TYPE: dict[DestinationType, str] = {
    "slack": "template-slack",
    "webhook": "template-webhook",
    "teams": "template-microsoft-teams",
}
DESTINATION_TYPE_BY_TEMPLATE_ID = {
    template_id: destination_type for destination_type, template_id in TEMPLATE_ID_BY_DESTINATION_TYPE.items()
}

WEBHOOK_HEADERS = {"Content-Type": "application/json", "X-PostHog-Webhook-Version": "1"}

# HogFunction.name is `models.CharField(max_length=400)` — clip rendered names to fit.
_HOG_FUNCTION_NAME_MAX_LEN = 400


@dataclass(frozen=True)
class EventKindSpec:
    """Product-authored content for one alert event kind (firing, resolved, ...)."""

    event_id: str
    display_kind: str
    header: str
    # Plain-text (label, value) pairs; each destination renders these in its own markup.
    details: tuple[tuple[str, str], ...]
    button_url: str
    button_label: str
    webhook_body: dict[str, Any]
    # e.g. "logs alert", "billing alert" — used in the HogFunction description.
    product_label: str = "alert"

    def destination_description(self, alert_name: str) -> str:
        return f'Sends {self.display_kind} notifications for {self.product_label} "{alert_name}".'


def clip_hog_function_name(name: str) -> str:
    if len(name) <= _HOG_FUNCTION_NAME_MAX_LEN:
        return name
    return name[: _HOG_FUNCTION_NAME_MAX_LEN - 1] + "…"


def destination_filter(alert_id: str, event_id: str) -> dict[str, Any]:
    """The linkage contract: dispatch finds destinations by this exact filter shape."""
    return {
        "events": [{"id": event_id, "type": "events"}],
        "properties": [
            {
                "key": ALERT_ID_PROPERTY,
                "value": alert_id,
                "operator": "exact",
                "type": "event",
            }
        ],
    }


def slack_body(spec: EventKindSpec) -> str:
    # Slack mrkdwn: *single asterisks* for bold, one line per detail.
    return "\n".join(f"*{label}:* {value}" for label, value in spec.details)


def slack_blocks(spec: EventKindSpec, context_elements: tuple[str, ...]) -> list[dict]:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": spec.header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": slack_body(spec)}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": element} for element in context_elements],
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


def teams_text(spec: EventKindSpec) -> str:
    # The Microsoft Teams template renders a single Adaptive Card TextBlock from `text`, so fold
    # the header, details, and action into one markdown string (the button becomes an inline link).
    # Adaptive Card markdown: **double asterisks** for bold, blank lines between paragraphs.
    details = "\n\n".join(f"**{label}:** {value}" for label, value in spec.details)
    return f"**{spec.header}**\n\n{details}\n\n[{spec.button_label}]({spec.button_url})"


def _base_config(
    *,
    team: Any,
    spec: EventKindSpec,
    alert_id: str,
    alert_name: str,
    name: str,
    template_id: str,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    return {
        "team": team,
        "type": "internal_destination",
        "enabled": True,
        "filters": destination_filter(alert_id, spec.event_id),
        "name": clip_hog_function_name(name),
        "description": spec.destination_description(alert_name),
        "template_id": template_id,
        "inputs": inputs,
    }


def build_slack_destination_config(
    *,
    team: Any,
    spec: EventKindSpec,
    alert_id: str,
    alert_name: str,
    name: str,
    slack_workspace_id: int,
    slack_channel_id: str,
    context_elements: tuple[str, ...],
) -> dict[str, Any]:
    return _base_config(
        team=team,
        spec=spec,
        alert_id=alert_id,
        alert_name=alert_name,
        name=name,
        template_id=TEMPLATE_ID_BY_DESTINATION_TYPE["slack"],
        inputs={
            "blocks": {"value": slack_blocks(spec, context_elements)},
            "text": {"value": spec.header},
            "slack_workspace": {"value": slack_workspace_id},
            "channel": {"value": slack_channel_id},
        },
    )


def build_webhook_destination_config(
    *,
    team: Any,
    spec: EventKindSpec,
    alert_id: str,
    alert_name: str,
    name: str,
    webhook_url: str,
) -> dict[str, Any]:
    return _base_config(
        team=team,
        spec=spec,
        alert_id=alert_id,
        alert_name=alert_name,
        name=name,
        template_id=TEMPLATE_ID_BY_DESTINATION_TYPE["webhook"],
        inputs={
            "body": {"value": spec.webhook_body},
            "url": {"value": webhook_url},
            "headers": {"value": WEBHOOK_HEADERS},
        },
    )


def build_teams_destination_config(
    *,
    team: Any,
    spec: EventKindSpec,
    alert_id: str,
    alert_name: str,
    name: str,
    webhook_url: str,
) -> dict[str, Any]:
    return _base_config(
        team=team,
        spec=spec,
        alert_id=alert_id,
        alert_name=alert_name,
        name=name,
        template_id=TEMPLATE_ID_BY_DESTINATION_TYPE["teams"],
        inputs={
            "webhookUrl": {"value": webhook_url},
            "text": {"value": teams_text(spec)},
        },
    )
