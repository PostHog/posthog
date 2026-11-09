"""Serializers for the notification destinations of a platform-owned alert.

A kind whose alerts the platform creates natively keeps its destinations as `AlertDestination` rows.
The platform alert API lists, adds and deletes them for every such kind, with the kind's own access rules.
"""

import re
from typing import Any, Final, cast

from django.db import models

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.integrations import IntegrationManager, IntegrationNotFound

from products.alerts_platform.backend.facade.api import redact_destination_data
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertEventKind,
    DestinationType,
    PagerDutyRegion,
    PagerDutySeverity,
    StoredAlertDestination,
)
from products.alerts_platform.backend.facade.delivery import refused_destination

# Each destination is another message every time the alert fires, so one alert has only a few.
MAX_DESTINATIONS_PER_ALERT: Final = 5
# Stops a malformed request becoming a huge query.
MAX_DESTINATION_IDS_PER_DELETE_REQUEST: Final = 100
# The types native delivery sends to. Email and in-app have no native sender yet.
PLATFORM_DESTINATION_TYPES: Final = (
    DestinationType.SLACK,
    DestinationType.WEBHOOK,
    DestinationType.TEAMS,
    DestinationType.DISCORD,
    DestinationType.PAGERDUTY,
)
# What a destination hears when the request names no kinds. An incident manager hears the trigger and
# resolve of every firing, which delivery sends it for firing and resolved.
_DEFAULT_EVENT_KINDS: Final[dict[DestinationType, tuple[AlertEventKind, ...]]] = {
    DestinationType.PAGERDUTY: (AlertEventKind.FIRING, AlertEventKind.RESOLVED),
}
_MESSAGE_EVENT_KINDS: Final = (
    AlertEventKind.FIRING,
    AlertEventKind.RESOLVED,
    AlertEventKind.ERRORED,
    AlertEventKind.BROKEN,
)
_WEBHOOK_FIELDS: Final = ("webhook_url",)
_PAGERDUTY_ROUTING_KEY_RE: Final = re.compile(r"[A-Za-z0-9]{32}")
_REQUIRED_FIELDS: Final[dict[DestinationType, tuple[str, ...]]] = {
    DestinationType.SLACK: ("slack_workspace_id", "slack_channel_id"),
    DestinationType.WEBHOOK: _WEBHOOK_FIELDS,
    DestinationType.TEAMS: _WEBHOOK_FIELDS,
    DestinationType.DISCORD: _WEBHOOK_FIELDS,
    DestinationType.PAGERDUTY: ("pagerduty_routing_key",),
}
# The fields each type stores. Redaction knows only its own type's credential, so a field of another
# type would be stored and then shown in full.
_FIELDS_BY_TYPE: Final[dict[DestinationType, tuple[str, ...]]] = {
    DestinationType.SLACK: ("slack_workspace_id", "slack_channel_id", "slack_channel_name"),
    DestinationType.WEBHOOK: _WEBHOOK_FIELDS,
    DestinationType.TEAMS: _WEBHOOK_FIELDS,
    DestinationType.DISCORD: _WEBHOOK_FIELDS,
    DestinationType.PAGERDUTY: ("pagerduty_routing_key", "pagerduty_severity", "pagerduty_region"),
}
# Choices classes for the serializers below. TextChoices supports this functional API at runtime, but
# its type stubs only describe member construction. The destination types carry their display labels,
# so the OpenAPI enum is named after this class. The others keep label equal to value, so they share
# the names their ENUM_NAME_OVERRIDES entries give them.
PlatformAlertDestinationType = cast(Any, models.TextChoices)(
    "PlatformAlertDestinationType",
    [(member.name, (member.value, member.label)) for member in PLATFORM_DESTINATION_TYPES],
)
PagerDutySeverityChoices = cast(Any, models.TextChoices)(
    "PagerDutySeverityChoices", [(member.name, (member.value, member.value)) for member in PagerDutySeverity]
)
PagerDutyRegionChoices = cast(Any, models.TextChoices)(
    "PagerDutyRegionChoices", [(member.name, (member.value, member.value)) for member in PagerDutyRegion]
)
PlatformAlertDestinationEventKind = cast(Any, models.TextChoices)(
    "PlatformAlertDestinationEventKind",
    [(member.name, (member.value, member.value)) for member in _MESSAGE_EVENT_KINDS],
)


class PlatformAlertDestinationSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the destination. Send it to the delete endpoint to remove it.")
    type = serializers.ChoiceField(
        choices=PlatformAlertDestinationType.choices, help_text="Notification destination type."
    )
    enabled = serializers.BooleanField(help_text="Whether the destination is sent to.")
    event_kinds = serializers.ListField(
        child=serializers.ChoiceField(choices=PlatformAlertDestinationEventKind.choices),
        help_text="The alert transitions the destination hears about. A PagerDuty destination hears the incident "
        "trigger and resolve of every firing.",
    )
    slack_workspace_id = serializers.IntegerField(
        required=False, help_text="Integration ID of the Slack workspace. Set when type=slack."
    )
    slack_channel_id = serializers.CharField(required=False, help_text="Slack channel ID. Set when type=slack.")
    slack_channel_name = serializers.CharField(
        required=False, help_text="Human-readable Slack channel name. Set when type=slack."
    )
    webhook_url = serializers.CharField(
        required=False,
        help_text="Webhook endpoint reduced to scheme and host. The path, query and userinfo carry the secret.",
    )
    pagerduty_routing_key = serializers.CharField(
        required=False, help_text="PagerDuty integration key reduced to its last four characters."
    )
    pagerduty_severity = serializers.ChoiceField(
        choices=PagerDutySeverityChoices.choices,
        required=False,
        help_text="Severity of the PagerDuty incident.",
    )
    pagerduty_region = serializers.ChoiceField(
        choices=PagerDutyRegionChoices.choices,
        required=False,
        help_text="PagerDuty service region the events go to.",
    )


class PlatformAlertCreateDestinationSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=PlatformAlertDestinationType.choices, help_text="Notification destination type."
    )
    slack_workspace_id = serializers.IntegerField(
        required=False, help_text="Integration ID for the Slack workspace. Required when type=slack."
    )
    slack_channel_id = serializers.CharField(required=False, help_text="Slack channel ID. Required when type=slack.")
    slack_channel_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Human-readable channel name for display."
    )
    webhook_url = serializers.URLField(
        required=False, help_text="HTTPS endpoint to post to. Required for webhook, teams and discord."
    )
    pagerduty_routing_key = serializers.CharField(
        required=False,
        trim_whitespace=True,
        help_text="Integration key of a PagerDuty Events API v2 integration. Required when type=pagerduty.",
    )
    pagerduty_severity = serializers.ChoiceField(
        choices=PagerDutySeverityChoices.choices,
        required=False,
        default=PagerDutySeverity.CRITICAL.value,
        help_text="Severity PagerDuty records on the incident. Used when type=pagerduty.",
    )
    pagerduty_region = serializers.ChoiceField(
        choices=PagerDutyRegionChoices.choices,
        required=False,
        default=PagerDutyRegion.US.value,
        help_text="PagerDuty service region of the account. Used when type=pagerduty.",
    )
    event_kinds = serializers.ListField(
        child=serializers.ChoiceField(choices=PlatformAlertDestinationEventKind.choices),
        required=False,
        min_length=1,
        help_text="The alert transitions to send about. Defaults to every kind, or to firing and resolved for "
        "PagerDuty, which then hears each incident's trigger and resolve.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        data = destination_data(attrs)
        routing_key = data.get("pagerduty_routing_key")
        if routing_key is not None and not _PAGERDUTY_ROUTING_KEY_RE.fullmatch(routing_key):
            raise ValidationError(
                {
                    "pagerduty_routing_key": "Enter the 32-character integration key of a PagerDuty Events API v2 integration."
                }
            )
        # The platform's write path checks the rest. Refusing here names the field at fault.
        if refusal := refused_destination(data):
            raise ValidationError({"webhook_url": refusal} if data.get("webhook_url") is not None else refusal)
        kinds = attrs.get("event_kinds") or _DEFAULT_EVENT_KINDS.get(data["type"], _MESSAGE_EVENT_KINDS)
        return {"data": data, "event_kinds": tuple(AlertEventKind(kind) for kind in kinds)}


class PlatformAlertDeleteDestinationSerializer(serializers.Serializer):
    destination_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=MAX_DESTINATION_IDS_PER_DELETE_REQUEST,
        help_text="IDs of the destinations to delete, as the list endpoint returns them.",
    )


def destination_data(attrs: dict[str, Any]) -> AlertDestinationData:
    """The fields of the chosen type from a validated request. Fields of other types are dropped."""
    destination_type = DestinationType(attrs["type"])
    # The PagerDuty fields have defaults, so they arrive for every type. Each type keeps only its own.
    data = cast(
        AlertDestinationData,
        {key: attrs[key] for key in _FIELDS_BY_TYPE[destination_type] if key in attrs},
    )
    data["type"] = destination_type
    # Checked before the view reads them, so a missing field answers 400 with its name.
    if missing := [key for key in _REQUIRED_FIELDS[destination_type] if not data.get(key)]:
        raise ValidationError(dict.fromkeys(missing, f"Required for {destination_type.label} destinations."))
    return data


def check_slack_workspace(team_id: int, data: AlertDestinationData) -> None:
    if data["type"] != DestinationType.SLACK:
        return
    # The accessor native delivery sends through, so a destination it would refuse is never saved.
    try:
        IntegrationManager.slack.oauth.get(team_id, data["slack_workspace_id"])
    except IntegrationNotFound:
        raise ValidationError({"slack_workspace_id": "Choose a Slack workspace connected to this project."})


def serialized_destination(destination: StoredAlertDestination) -> dict[str, Any]:
    return {
        "id": destination.id,
        "enabled": destination.enabled,
        "event_kinds": [kind.value for kind in destination.event_kinds],
        **redact_destination_data(destination.data),
    }
