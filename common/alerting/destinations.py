"""Shared builders for alert notification destinations (CDP internal_destination HogFunctions).

Every alerting product delivers notifications the same way: an internal event per
alert-event kind (firing, resolved, errored, auto-disabled), consumed by one
HogFunction per destination per kind, linked to the alert via an `alert_id`
property filter. This module owns that wiring — the filter shape, the template
input structure per destination type, and the message scaffolding — so dispatch
and destinations can never drift apart per product.

Products own the content: their `EventKindSpec` table (event names, headers,
detail rows, payload data) and the display name of each HogFunction.

Pure Python — the `team` value is carried opaquely on `AlertDestinationConfig`,
never inside the serializer payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AlertDestinationTemplate(StrEnum):
    SLACK = "template-slack"
    DISCORD = "template-discord"
    WEBHOOK = "template-webhook"
    TEAMS = "template-microsoft-teams"


WEBHOOK_HEADERS = {"Content-Type": "application/json", "X-PostHog-Webhook-Version": "1"}

# HogFunction.name is `models.CharField(max_length=400)` — clip rendered names to fit.
_HOG_FUNCTION_NAME_MAX_LEN = 400


@dataclass(frozen=True)
class AlertDestinationConfig:
    """Keeps the team outside the serializer payload."""

    team: Any
    payload: dict[str, Any]


@dataclass(frozen=True)
class Button:
    url: str
    label: str


@dataclass(frozen=True)
class EventKindSpec:
    """Keeps product content within the shared destination rendering vocabulary."""

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
    # Free-form prose lines rendered above the detail rows (one line each).
    body_lines: tuple[str, ...] = ()
    # Action buttons rendered after the primary button_url/button_label one.
    extra_buttons: tuple[Button, ...] = ()

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
                "key": "alert_id",
                "value": alert_id,
                "operator": "exact",
                "type": "event",
            }
        ],
    }


def slack_body(spec: EventKindSpec) -> str:
    # Slack mrkdwn: *single asterisks* for bold, one line per detail. Prose lines
    # come first, separated from the detail rows by a blank line.
    parts = []
    if spec.body_lines:
        parts.append("\n".join(spec.body_lines))
    if spec.details:
        parts.append("\n".join(f"*{label}:* {value}" for label, value in spec.details))
    return "\n\n".join(parts)


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
                    "url": button.url,
                    "text": {"text": button.label, "type": "plain_text"},
                    "type": "button",
                }
                for button in (Button(url=spec.button_url, label=spec.button_label), *spec.extra_buttons)
            ],
        },
    ]


def teams_text(spec: EventKindSpec) -> str:
    # The Microsoft Teams template renders a single Adaptive Card TextBlock from `text`, so fold
    # the header, prose, details, and actions into one markdown string (buttons become inline links).
    # Adaptive Card markdown: **double asterisks** for bold, blank lines between paragraphs.
    parts = [f"**{spec.header}**"]
    parts.extend(spec.body_lines)
    if spec.details:
        parts.append("\n\n".join(f"**{label}:** {value}" for label, value in spec.details))
    parts.append(
        " · ".join(
            f"[{button.label}]({button.url})"
            for button in (Button(url=spec.button_url, label=spec.button_label), *spec.extra_buttons)
        )
    )
    return "\n\n".join(parts)


def _base_config(
    *,
    team: Any,
    spec: EventKindSpec,
    alert_id: str,
    alert_name: str,
    name: str,
    template_id: str,
    inputs: dict[str, Any],
) -> AlertDestinationConfig:
    return AlertDestinationConfig(
        team=team,
        payload={
            "type": "internal_destination",
            "enabled": True,
            "filters": destination_filter(alert_id, spec.event_id),
            "name": clip_hog_function_name(name),
            "description": spec.destination_description(alert_name),
            "template_id": template_id,
            "inputs": inputs,
        },
    )


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
) -> AlertDestinationConfig:
    return _base_config(
        team=team,
        spec=spec,
        alert_id=alert_id,
        alert_name=alert_name,
        name=name,
        template_id=AlertDestinationTemplate.SLACK,
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
) -> AlertDestinationConfig:
    return _base_config(
        team=team,
        spec=spec,
        alert_id=alert_id,
        alert_name=alert_name,
        name=name,
        template_id=AlertDestinationTemplate.WEBHOOK,
        inputs={
            "body": {"value": spec.webhook_body},
            "url": {"value": webhook_url},
            "headers": {"value": WEBHOOK_HEADERS},
        },
    )


def build_discord_destination_config(
    *,
    team: Any,
    spec: EventKindSpec,
    alert_id: str,
    alert_name: str,
    name: str,
    webhook_url: str,
) -> AlertDestinationConfig:
    return _base_config(
        team=team,
        spec=spec,
        alert_id=alert_id,
        alert_name=alert_name,
        name=name,
        template_id=AlertDestinationTemplate.DISCORD,
        inputs={
            "webhookUrl": {"value": webhook_url},
            "content": {"value": teams_text(spec)},
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
) -> AlertDestinationConfig:
    return _base_config(
        team=team,
        spec=spec,
        alert_id=alert_id,
        alert_name=alert_name,
        name=name,
        template_id=AlertDestinationTemplate.TEAMS,
        inputs={
            "webhookUrl": {"value": webhook_url},
            "text": {"value": teams_text(spec)},
        },
    )
