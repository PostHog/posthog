"""Shared configuration builders for alert destinations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from django.db import models


class DestinationType(models.TextChoices):
    SLACK = "slack", "Slack"
    DISCORD = "discord", "Discord"
    WEBHOOK = "webhook", "Webhook"
    TEAMS = "teams", "Microsoft Teams"


class AlertDestinationTemplate(StrEnum):
    SLACK = "template-slack"
    DISCORD = "template-discord"
    WEBHOOK = "template-webhook"
    TEAMS = "template-microsoft-teams"


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
