"""Shared configuration builders for alert destinations."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, ClassVar
from urllib.parse import urlsplit

from products.alerts.backend.facade.contracts import (
    AlertDestinationAction,
    AlertDestinationConfig,
    AlertDestinationData,
    AlertDestinationValidationError,
    DestinationType,
    EventKindSpec,
    PagerDutyRegion,
    PagerDutySeverity,
)

WEBHOOK_HEADERS = {"Content-Type": "application/json", "X-PostHog-Webhook-Version": "1"}

_HOG_FUNCTION_NAME_MAX_LEN = 400

# An Events API v2 integration key as PagerDuty issues it.
_PAGERDUTY_ROUTING_KEY_RE = re.compile(r"[A-Za-z0-9]{32}")


def clip_hog_function_name(name: str) -> str:
    if len(name) <= _HOG_FUNCTION_NAME_MAX_LEN:
        return name
    return name[: _HOG_FUNCTION_NAME_MAX_LEN - 1] + "…"


def destination_filter(alert_id: str, event_id: str) -> dict[str, Any]:
    return {
        "source": "internal-events",
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


def spec_actions(spec: EventKindSpec) -> tuple[AlertDestinationAction, ...]:
    return (
        AlertDestinationAction(url=spec.primary_action_url, label=spec.primary_action_label),
        *spec.additional_actions,
    )


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
                for action in spec_actions(spec)
            ],
        },
    ]


def teams_text(spec: EventKindSpec) -> str:
    parts = [f"**{spec.header}**"]
    parts.extend(spec.intro_lines)
    if spec.details:
        parts.append("\n\n".join(f"**{label}:** {value}" for label, value in spec.details))
    parts.append(" · ".join(f"[{action.label}]({action.url})" for action in spec_actions(spec)))
    return "\n\n".join(parts)


def pagerduty_summary(spec: EventKindSpec) -> str:
    """The incident title: the header, plus the first detail so the page says what breached."""
    if not spec.details:
        return spec.header
    return f"{spec.header}: {spec.details[0][1]}"


def pagerduty_custom_details(spec: EventKindSpec) -> dict[str, str]:
    details = dict(spec.details)
    if spec.intro_lines:
        details = {"Details": "\n".join(spec.intro_lines), **details}
    return details


def pagerduty_links(spec: EventKindSpec) -> list[dict[str, str]]:
    return [{"href": action.url, "text": action.label} for action in spec_actions(spec)]


def _input_value(inputs: dict[str, Any], key: str) -> Any:
    entry = inputs.get(key)
    return entry.get("value") if isinstance(entry, dict) else None


class DestinationSpec(ABC):
    """Everything one destination type knows about itself: how it is stored as a
    HogFunction, how it is read back, and how it is safe to show in a read response."""

    type: ClassVar[DestinationType]
    template_id: ClassVar[str]
    required_fields: ClassVar[tuple[str, ...]]

    def validate(self, data: AlertDestinationData) -> None:
        """Raise `AlertDestinationValidationError` when the payload cannot become a destination of this type."""
        missing_fields = tuple(field for field in self.required_fields if not data.get(field))
        if len(missing_fields) == 1:
            missing_field = missing_fields[0]
            raise AlertDestinationValidationError(
                f"{missing_field} is required for {self.type.label} destinations.", field=missing_field
            )
        if missing_fields:
            formatted_fields = " and ".join(missing_fields)
            raise AlertDestinationValidationError(f"{self.type.label} destinations require {formatted_fields}.")

    def handles(self, event_kind_spec: EventKindSpec) -> bool:
        """Whether this destination type has something to send for one event kind."""
        return True

    @abstractmethod
    def build_name(self, data: AlertDestinationData) -> str: ...

    @abstractmethod
    def build_inputs(
        self,
        event_kind_spec: EventKindSpec,
        data: AlertDestinationData,
        *,
        alert_id: str,
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
        alert_id: str,
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
        alert_id: str,
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
        alert_id: str,
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
        alert_id: str,
        slack_context_elements: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "webhookUrl": {"value": data["webhook_url"]},
            "text": {"value": teams_text(event_kind_spec)},
        }


class PagerDutyDestination(DestinationSpec):
    """One incident per alert: the firing kind triggers it and the resolved kind resolves it,
    tied together by a deduplication key derived from the alert id."""

    type = DestinationType.PAGERDUTY
    template_id = "template-pagerduty"
    required_fields = ("pagerduty_routing_key",)

    def validate(self, data: AlertDestinationData) -> None:
        super().validate(data)
        if not _PAGERDUTY_ROUTING_KEY_RE.fullmatch(data["pagerduty_routing_key"]):
            raise AlertDestinationValidationError(
                "Enter the 32-character integration key of a PagerDuty Events API v2 integration.",
                field="pagerduty_routing_key",
            )
        severity = data.get("pagerduty_severity")
        if severity is not None and severity not in PagerDutySeverity:
            choices = ", ".join(choice.value for choice in PagerDutySeverity)
            raise AlertDestinationValidationError(f"Choose a severity: {choices}.", field="pagerduty_severity")
        region = data.get("pagerduty_region")
        if region is not None and region not in PagerDutyRegion:
            choices = ", ".join(choice.value for choice in PagerDutyRegion)
            raise AlertDestinationValidationError(f"Choose a region: {choices}.", field="pagerduty_region")

    def handles(self, event_kind_spec: EventKindSpec) -> bool:
        return event_kind_spec.incident_action is not None

    def build_name(self, data: AlertDestinationData) -> str:
        return f"PagerDuty {_redact_routing_key(data['pagerduty_routing_key'])}"

    def build_inputs(
        self,
        event_kind_spec: EventKindSpec,
        data: AlertDestinationData,
        *,
        alert_id: str,
        slack_context_elements: tuple[str, ...],
    ) -> dict[str, Any]:
        if event_kind_spec.incident_action is None:
            raise ValueError(f"PagerDuty has nothing to send for the {event_kind_spec.display_kind} event kind.")
        return {
            "routing_key": {"value": data["pagerduty_routing_key"]},
            "region": {"value": data.get("pagerduty_region") or PagerDutyRegion.US.value},
            "event_action": {"value": event_kind_spec.incident_action.value},
            "dedup_key": {"value": pagerduty_dedup_key(alert_id)},
            "summary": {"value": pagerduty_summary(event_kind_spec)},
            "source": {"value": "{project.name}"},
            "severity": {"value": data.get("pagerduty_severity") or PagerDutySeverity.CRITICAL.value},
            "custom_details": {"value": pagerduty_custom_details(event_kind_spec)},
            "links": {"value": pagerduty_links(event_kind_spec)},
            "client_url": {"value": event_kind_spec.primary_action_url},
        }

    def read(self, inputs: dict[str, Any]) -> AlertDestinationData:
        data: AlertDestinationData = {"type": self.type}
        routing_key = _input_value(inputs, "routing_key")
        # Without the key two PagerDuty destinations cannot be told apart, so a config that
        # lacks it reads as unreadable rather than as "the same as every other one".
        if not isinstance(routing_key, str) or not routing_key:
            return data
        data["pagerduty_routing_key"] = routing_key
        severity = _input_value(inputs, "severity")
        region = _input_value(inputs, "region")
        if isinstance(severity, str):
            data["pagerduty_severity"] = severity
        if isinstance(region, str):
            data["pagerduty_region"] = region
        return data

    def redact(self, data: AlertDestinationData) -> AlertDestinationData:
        routing_key = data.get("pagerduty_routing_key")
        if routing_key is None:
            return data
        redacted = data.copy()
        redacted["pagerduty_routing_key"] = _redact_routing_key(routing_key)
        return redacted


def pagerduty_dedup_key(alert_id: str) -> str:
    return f"posthog-alert-{alert_id}"


def _redact_routing_key(value: str) -> str:
    """Keep the tail a person needs to tell two integration keys apart."""
    return f"••••{value[-4:]}"


DESTINATION_SPECS: dict[DestinationType, DestinationSpec] = {
    spec.type: spec
    for spec in (
        SlackDestination(),
        DiscordDestination(),
        WebhookDestination(),
        TeamsDestination(),
        PagerDutyDestination(),
    )
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
    DESTINATION_SPECS[destination_type].validate(data)


def destination_handles_event_kind(destination_type: DestinationType, spec: EventKindSpec) -> bool:
    return DESTINATION_SPECS[destination_type].handles(spec)


def build_alert_destination_config(
    *,
    spec: EventKindSpec,
    alert_id: str,
    alert_name: str,
    data: AlertDestinationData,
    slack_context_elements: tuple[str, ...],
) -> AlertDestinationConfig:
    destination_spec = DESTINATION_SPECS[data["type"]]
    if not destination_spec.handles(spec):
        raise ValueError(
            f"{destination_spec.type.label} destinations have nothing to send for the {spec.display_kind} event kind. "
            "Filter event kinds with destination_handles_event_kind first."
        )
    product_name = spec.product_label.capitalize()
    destination_name = destination_spec.build_name(data)

    return AlertDestinationConfig(
        payload={
            "type": "internal_destination",
            "enabled": True,
            "filters": destination_filter(alert_id, spec.event_id),
            "name": clip_hog_function_name(f"{product_name} — {alert_name} ({spec.display_kind}) → {destination_name}"),
            "description": spec.destination_description(alert_name),
            "template_id": destination_spec.template_id,
            "inputs": destination_spec.build_inputs(
                spec, data, alert_id=alert_id, slack_context_elements=slack_context_elements
            ),
        },
    )
