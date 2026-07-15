"""Shared configuration builders for alert destinations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict

from django.db import models


class DestinationType(models.TextChoices):
    SLACK = "slack", "Slack"
    DISCORD = "discord", "Discord"
    WEBHOOK = "webhook", "Webhook"
    TEAMS = "teams", "Microsoft Teams"


DESTINATION_TEMPLATE_IDS: dict[DestinationType, str] = {
    DestinationType.SLACK: "template-slack",
    DestinationType.DISCORD: "template-discord",
    DestinationType.WEBHOOK: "template-webhook",
    DestinationType.TEAMS: "template-microsoft-teams",
}

DESTINATION_REQUIRED_FIELDS: dict[DestinationType, tuple[str, ...]] = {
    DestinationType.SLACK: ("slack_workspace_id", "slack_channel_id"),
    DestinationType.DISCORD: ("webhook_url",),
    DestinationType.WEBHOOK: ("webhook_url",),
    DestinationType.TEAMS: ("webhook_url",),
}


class AlertDestinationData(TypedDict):
    type: DestinationType
    slack_workspace_id: NotRequired[int]
    slack_channel_id: NotRequired[str]
    slack_channel_name: NotRequired[str]
    webhook_url: NotRequired[str]


class AlertDestinationValidationError(Exception):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.message = message
        self.field = field
        super().__init__(message)


WEBHOOK_HEADERS = {"Content-Type": "application/json", "X-PostHog-Webhook-Version": "1"}

_HOG_FUNCTION_NAME_MAX_LEN = 400


@dataclass(frozen=True)
class AlertDestinationConfig:
    team: Any
    payload: dict[str, Any]


@dataclass(frozen=True)
class AlertDestinationAction:
    url: str
    label: str


@dataclass(frozen=True)
class EventKindSpec:
    event_id: str
    display_kind: str
    header: str
    details: tuple[tuple[str, str], ...]
    primary_action_url: str
    primary_action_label: str
    webhook_body: dict[str, Any]
    product_label: str = "alert"
    intro_lines: tuple[str, ...] = ()
    additional_actions: tuple[AlertDestinationAction, ...] = ()

    def destination_description(self, alert_name: str) -> str:
        return f'Sends {self.display_kind} notifications for {self.product_label} "{alert_name}".'


def clip_hog_function_name(name: str) -> str:
    if len(name) <= _HOG_FUNCTION_NAME_MAX_LEN:
        return name
    return name[: _HOG_FUNCTION_NAME_MAX_LEN - 1] + "…"


def destination_filter(alert_id: str, event_id: str) -> dict[str, Any]:
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
    parts = []
    if spec.intro_lines:
        parts.append("\n".join(spec.intro_lines))
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
                    "url": action.url,
                    "text": {"text": action.label, "type": "plain_text"},
                    "type": "button",
                }
                for action in (
                    AlertDestinationAction(url=spec.primary_action_url, label=spec.primary_action_label),
                    *spec.additional_actions,
                )
            ],
        },
    ]


def teams_text(spec: EventKindSpec) -> str:
    parts = [f"**{spec.header}**"]
    parts.extend(spec.intro_lines)
    if spec.details:
        parts.append("\n\n".join(f"**{label}:** {value}" for label, value in spec.details))
    parts.append(
        " · ".join(
            f"[{action.label}]({action.url})"
            for action in (
                AlertDestinationAction(url=spec.primary_action_url, label=spec.primary_action_label),
                *spec.additional_actions,
            )
        )
    )
    return "\n\n".join(parts)


def validate_destination_data(
    data: AlertDestinationData,
    *,
    allowed_destination_types: Sequence[DestinationType],
) -> None:
    raw_destination_type = data.get("type")
    destination_type = next((choice for choice in allowed_destination_types if choice == raw_destination_type), None)
    if destination_type is None:
        choices = ", ".join(f"{choice.label} ({choice.value})" for choice in allowed_destination_types)
        raise AlertDestinationValidationError(f"Choose a supported destination type: {choices}.", field="type")

    missing_fields = tuple(field for field in DESTINATION_REQUIRED_FIELDS[destination_type] if not data.get(field))
    if len(missing_fields) == 1:
        missing_field = missing_fields[0]
        raise AlertDestinationValidationError(
            f"{missing_field} is required for {destination_type.label} destinations.", field=missing_field
        )
    if missing_fields:
        formatted_fields = " and ".join(missing_fields)
        raise AlertDestinationValidationError(f"{destination_type.label} destinations require {formatted_fields}.")


def build_alert_destination_config(
    *,
    team: Any,
    spec: EventKindSpec,
    alert_id: str,
    alert_name: str,
    data: AlertDestinationData,
    slack_context_elements: tuple[str, ...],
) -> AlertDestinationConfig:
    destination_type = data["type"]
    product_name = spec.product_label.capitalize()

    if destination_type == DestinationType.SLACK:
        channel_display = data.get("slack_channel_name") or "channel"
        destination_name = f"Slack #{channel_display}"
        inputs = {
            "blocks": {"value": slack_blocks(spec, slack_context_elements)},
            "text": {"value": spec.header},
            "slack_workspace": {"value": data["slack_workspace_id"]},
            "channel": {"value": data["slack_channel_id"]},
        }
    elif destination_type == DestinationType.WEBHOOK:
        destination_name = f"Webhook {data['webhook_url']}"
        inputs = {
            "body": {"value": spec.webhook_body},
            "url": {"value": data["webhook_url"]},
            "headers": {"value": WEBHOOK_HEADERS},
        }
    elif destination_type == DestinationType.DISCORD:
        destination_name = "Discord"
        inputs = {
            "content": {"value": teams_text(spec)},
            "webhookUrl": {"value": data["webhook_url"]},
        }
    else:
        destination_name = "Microsoft Teams"
        inputs = {
            "webhookUrl": {"value": data["webhook_url"]},
            "text": {"value": teams_text(spec)},
        }

    return AlertDestinationConfig(
        team=team,
        payload={
            "type": "internal_destination",
            "enabled": True,
            "filters": destination_filter(alert_id, spec.event_id),
            "name": clip_hog_function_name(f"{product_name} — {alert_name} ({spec.display_kind}) → {destination_name}"),
            "description": spec.destination_description(alert_name),
            "template_id": DESTINATION_TEMPLATE_IDS[destination_type],
            "inputs": inputs,
        },
    )
