"""Serializers for Conversations widget API."""

from rest_framework import serializers

from posthog.api.utils import on_permitted_recording_domain
from posthog.models import Team

from products.conversations.backend.models.constants import Status


class WidgetMessageSerializer(serializers.Serializer):
    """Serializer for incoming widget messages."""

    widget_session_id = serializers.UUIDField(required=True, help_text="Random UUID for access control")
    distinct_id = serializers.CharField(required=True, max_length=400, help_text="PostHog distinct_id")
    message = serializers.CharField(required=True, max_length=5000, help_text="Message content")
    traits = serializers.DictField(required=False, default=dict, help_text="Customer traits")

    def validate_message(self, value):
        """Ensure message is not empty after stripping."""
        if not value or not value.strip():
            raise serializers.ValidationError("Message content is required")
        return value.strip()

    def validate_traits(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("traits must be a dictionary")

        if len(value) > 50:
            raise serializers.ValidationError(f"Too many traits: {len(value)} (max 50)")

        validated = {}
        for key, val in value.items():
            # Validate key is a string with reasonable length
            if not isinstance(key, str):
                continue
            if len(key) > 200:
                raise serializers.ValidationError(f"Trait key too long: '{key[:50]}...' (max 200 chars)")

            # Only allow simple types for MVP
            if not isinstance(val, str | int | float | bool | type(None)):
                continue

            # Convert to string and validate length
            str_value = str(val) if val is not None else None
            if str_value and len(str_value) > 500:
                raise serializers.ValidationError(f"Trait value too long for '{key}' (max 500 chars)")

            validated[key] = str_value

        return validated


class WidgetMessagesQuerySerializer(serializers.Serializer):
    """Serializer for fetching messages from a ticket."""

    widget_session_id = serializers.UUIDField(required=True)
    after = serializers.DateTimeField(required=False, allow_null=True)


class WidgetTicketsQuerySerializer(serializers.Serializer):
    """Serializer for fetching tickets for a widget session."""

    widget_session_id = serializers.UUIDField(required=True)
    status = serializers.ChoiceField(
        choices=[s.value for s in Status],
        required=False,
        allow_null=True,
        help_text="Filter by ticket status",
    )
    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=500)
    offset = serializers.IntegerField(required=False, default=0, min_value=0)


class WidgetMarkReadSerializer(serializers.Serializer):
    """Serializer for marking a ticket as read."""

    widget_session_id = serializers.UUIDField(required=True)


def validate_origin(request, team: Team) -> bool:
    """
    Validate request origin to prevent token reuse on unauthorized domains.
    Checks against team.conversations_settings.widget_domains if configured.
    Empty list = allow all domains.
    """
    settings = team.conversations_settings or {}
    domains = settings.get("widget_domains") or []

    if not domains:
        return True

    return on_permitted_recording_domain(domains, request._request)
