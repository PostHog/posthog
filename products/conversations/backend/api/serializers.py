"""Serializers for Conversations API."""

from rest_framework import serializers

from posthog.api.utils import on_permitted_recording_domain
from posthog.models import Team

from products.conversations.backend.models import TicketAssignment
from products.conversations.backend.models.constants import Status


class TicketAssignmentSerializer(serializers.ModelSerializer):
    """Serializer for ticket assignment (user or role)."""

    id = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()

    class Meta:
        model = TicketAssignment
        fields = ["id", "type"]

    def get_id(self, obj):
        return obj.user_id if obj.user_id else str(obj.role_id) if obj.role_id else None

    def get_type(self, obj):
        return "role" if obj.role_id else "user"


class WidgetMessageSerializer(serializers.Serializer):
    """Serializer for incoming widget messages."""

    widget_session_id = serializers.UUIDField(required=True, help_text="Random UUID for access control")
    distinct_id = serializers.CharField(required=True, max_length=400, help_text="PostHog distinct_id")
    message = serializers.CharField(required=True, max_length=5000, help_text="Message content")
    traits = serializers.DictField(required=False, default=dict, help_text="Customer traits")
    session_id = serializers.CharField(required=False, max_length=64, allow_null=True, help_text="PostHog session ID")
    session_context = serializers.DictField(
        required=False, default=dict, help_text="Session context (replay URL, current URL, etc.)"
    )

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

    def validate_session_context(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("session_context must be a dictionary")

        if len(value) > 20:
            raise serializers.ValidationError(f"Too many session context fields: {len(value)} (max 20)")

        validated = {}
        for key, val in value.items():
            # Validate key
            if not isinstance(key, str):
                continue
            if len(key) > 100:
                raise serializers.ValidationError(f"Session context key too long: '{key[:50]}...' (max 100 chars)")

            # Allow simple types and validate length
            if not isinstance(val, str | int | float | bool | type(None)):
                continue

            # Validate string length for string values
            if isinstance(val, str) and len(val) > 2000:  # URLs can be long
                raise serializers.ValidationError(f"Session context value too long for '{key}' (max 2000 chars)")

            validated[key] = val

        return validated


class WidgetMessagesQuerySerializer(serializers.Serializer):
    """Serializer for fetching messages from a ticket."""

    widget_session_id = serializers.UUIDField(required=True)
    after = serializers.DateTimeField(required=False, allow_null=True)
    limit = serializers.IntegerField(required=False, default=500, min_value=1, max_value=500)


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
