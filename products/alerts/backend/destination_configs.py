"""Shared configuration builders for alert destinations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, NotRequired, TypedDict
from urllib.parse import urlsplit

from django.db import models


class DestinationType(models.TextChoices):
    SLACK = "slack", "Slack"
    DISCORD = "discord", "Discord"
    WEBHOOK = "webhook", "Webhook"
    TEAMS = "teams", "Microsoft Teams"


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


def _input_value(inputs: dict[str, Any], key: str) -> Any:
    entry = inputs.get(key)
    return entry.get("value") if isinstance(entry, dict) else None


class DestinationSpec(ABC):
    """Everything one destination type knows about itself: how it is stored as a
    HogFunction, how it is read back, and how it is safe to show in a read response."""

    type: ClassVar[DestinationType]
    template_id: ClassVar[str]
    required_fields: ClassVar[tuple[str, ...]]

    @abstractmethod
    def build_name(self, data: AlertDestinationData) -> str: ...

    @abstractmethod
    def build_inputs(
        self,
        event_kind_spec: EventKindSpec,
        data: AlertDestinationData,
        *,
        slack_context_elements: tuple[str, ...],
    ) -> dict[str, Any]: ...

    @abstractmethod
    def read(self, inputs: dict[str, Any]) -> AlertDestinationData: ...

    def redact(self, data: AlertDestinationData) -> AlertDestinationData:
        return data


class SlackDestination(DestinationSpec):
    type = DestinationType.SLACK
    template_id = "template-slack"
    required_fields = ("slack_workspace_id", "slack_channel_id")

    def build_name(self, data: AlertDestinationData) -> str:
        return f"Slack #{data.get('slack_channel_name') or 'channel'}"

    def build_inputs(
        self,
        event_kind_spec: EventKindSpec,
        data: AlertDestinationData,
        *,
        slack_context_elements: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "blocks": {"value": slack_blocks(event_kind_spec, slack_context_elements)},
            "text": {"value": event_kind_spec.header},
            "slack_workspace": {"value": data["slack_workspace_id"]},
            "channel": {"value": data["slack_channel_id"]},
        }

    def read(self, inputs: dict[str, Any]) -> AlertDestinationData:
        data: AlertDestinationData = {"type": self.type}
        slack_workspace_id = _input_value(inputs, "slack_workspace")
        slack_channel_id = _input_value(inputs, "channel")
        if isinstance(slack_workspace_id, int):
            data["slack_workspace_id"] = slack_workspace_id
        if isinstance(slack_channel_id, str):
            data["slack_channel_id"] = slack_channel_id
        return data


class _WebhookUrlDestination(DestinationSpec):
    """Base for the types whose whole configuration is one webhook URL."""

    required_fields = ("webhook_url",)
    url_input_key: ClassVar[str]

    def read(self, inputs: dict[str, Any]) -> AlertDestinationData:
        data: AlertDestinationData = {"type": self.type}
        webhook_url = _input_value(inputs, self.url_input_key)
        if isinstance(webhook_url, str):
            data["webhook_url"] = webhook_url
        return data

    def redact(self, data: AlertDestinationData) -> AlertDestinationData:
        webhook_url = data.get("webhook_url")
        if webhook_url is None:
            return data
        redacted = data.copy()
        redacted["webhook_url"] = _redact_url(webhook_url)
        return redacted


class WebhookDestination(_WebhookUrlDestination):
    type = DestinationType.WEBHOOK
    template_id = "template-webhook"
    url_input_key = "url"

    def build_name(self, data: AlertDestinationData) -> str:
        return f"Webhook {data['webhook_url']}"

    def build_inputs(
        self,
        event_kind_spec: EventKindSpec,
        data: AlertDestinationData,
        *,
        slack_context_elements: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "body": {"value": event_kind_spec.webhook_body},
            "url": {"value": data["webhook_url"]},
            "headers": {"value": WEBHOOK_HEADERS},
        }


class DiscordDestination(_WebhookUrlDestination):
    type = DestinationType.DISCORD
    template_id = "template-discord"
    url_input_key = "webhookUrl"

    def build_name(self, data: AlertDestinationData) -> str:
        return "Discord"

    def build_inputs(
        self,
        event_kind_spec: EventKindSpec,
        data: AlertDestinationData,
        *,
        slack_context_elements: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "content": {"value": teams_text(event_kind_spec)},
            "webhookUrl": {"value": data["webhook_url"]},
        }


class TeamsDestination(_WebhookUrlDestination):
    type = DestinationType.TEAMS
    template_id = "template-microsoft-teams"
    url_input_key = "webhookUrl"

    def build_name(self, data: AlertDestinationData) -> str:
        return "Microsoft Teams"

    def build_inputs(
        self,
        event_kind_spec: EventKindSpec,
        data: AlertDestinationData,
        *,
        slack_context_elements: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "webhookUrl": {"value": data["webhook_url"]},
            "text": {"value": teams_text(event_kind_spec)},
        }


DESTINATION_SPECS: dict[DestinationType, DestinationSpec] = {
    spec.type: spec for spec in (SlackDestination(), DiscordDestination(), WebhookDestination(), TeamsDestination())
}

SPEC_BY_TEMPLATE_ID: dict[str, DestinationSpec] = {spec.template_id: spec for spec in DESTINATION_SPECS.values()}


def _redact_url(value: str) -> str:
    """Keep only the parts a person needs to tell two destinations apart. The path,
    query and userinfo carry the channel secret for every webhook-style provider."""
    try:
        parsed = urlsplit(value)
        scheme, hostname, port = parsed.scheme, parsed.hostname, parsed.port
    except ValueError:
        return "<redacted>"
    if not scheme or not hostname:
        return "<redacted>"
    authority = f"{hostname}:{port}" if port is not None else hostname
    return f"{scheme}://{authority}"


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

    missing_fields = tuple(
        field for field in DESTINATION_SPECS[destination_type].required_fields if not data.get(field)
    )
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
    destination_spec = DESTINATION_SPECS[data["type"]]
    product_name = spec.product_label.capitalize()
    destination_name = destination_spec.build_name(data)

    return AlertDestinationConfig(
        team=team,
        payload={
            "type": "internal_destination",
            "enabled": True,
            "filters": destination_filter(alert_id, spec.event_id),
            "name": clip_hog_function_name(f"{product_name} — {alert_name} ({spec.display_kind}) → {destination_name}"),
            "description": spec.destination_description(alert_name),
            "template_id": destination_spec.template_id,
            "inputs": destination_spec.build_inputs(spec, data, slack_context_elements=slack_context_elements),
        },
    )
