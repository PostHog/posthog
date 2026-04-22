"""Serializers for Conversations API."""

from urllib.parse import urlparse

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.api.utils import on_permitted_recording_domain
from posthog.models import Team

from products.conversations.backend.models import TicketAssignment
from products.conversations.backend.models.constants import Status


class TicketAssignmentSerializer(serializers.ModelSerializer):
    """Serializer for ticket assignment (user or role)."""

    id = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()

    class Meta:
        model = TicketAssignment
        fields = ["id", "type", "user", "role"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_id(self, obj):
        return obj.user_id if obj.user_id else str(obj.role_id) if obj.role_id else None

    @extend_schema_field(serializers.CharField())
    def get_type(self, obj):
        return "role" if obj.role_id else "user"

    @extend_schema_field(serializers.DictField(child=serializers.CharField(), allow_null=True))
    def get_user(self, obj):
        if obj.user_id and obj.user:
            return {"email": obj.user.email}
        return None

    @extend_schema_field(serializers.DictField(child=serializers.CharField(), allow_null=True))
    def get_role(self, obj):
        if obj.role_id and obj.role:
            return {"name": obj.role.name}
        return None


class WidgetAuthSerializer(serializers.Serializer):
    """Shared auth fields: request must carry widget_session_id or HMAC identity fields."""

    widget_session_id = serializers.UUIDField(required=False, help_text="Random UUID for access control")
    identity_distinct_id = serializers.CharField(
        required=False, max_length=400, help_text="Verified distinct_id (requires identity_hash)"
    )
    identity_hash = serializers.CharField(
        required=False,
        min_length=64,
        max_length=64,
        help_text="HMAC-SHA256 of identity_distinct_id using team secret_api_token",
    )

    def validate(self, data):
        has_session = "widget_session_id" in data
        has_identity = "identity_distinct_id" in data and "identity_hash" in data
        if not has_session and not has_identity:
            raise serializers.ValidationError(
                "Either widget_session_id or both identity_distinct_id and identity_hash are required"
            )
        return data


class WidgetMessageSerializer(WidgetAuthSerializer):
    """Serializer for incoming widget messages."""

    distinct_id = serializers.CharField(required=False, max_length=400, help_text="PostHog distinct_id")
    message = serializers.CharField(required=True, max_length=5000, help_text="Message content")
    traits = serializers.DictField(required=False, default=dict, help_text="Customer traits")
    session_id = serializers.CharField(required=False, max_length=64, allow_null=True, help_text="PostHog session ID")
    session_context = serializers.DictField(
        required=False, default=dict, help_text="Session context (replay URL, current URL, etc.)"
    )

    def validate(self, data):
        data = super().validate(data)
        has_session = "widget_session_id" in data
        has_identity = "identity_distinct_id" in data and "identity_hash" in data
        if has_identity and "distinct_id" not in data:
            data["distinct_id"] = data["identity_distinct_id"]
        elif has_session and not has_identity and "distinct_id" not in data:
            raise serializers.ValidationError("distinct_id is required when using widget_session_id")
        return data

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


class WidgetMessagesQuerySerializer(WidgetAuthSerializer):
    """Serializer for fetching messages from a ticket."""

    after = serializers.DateTimeField(required=False, allow_null=True)
    limit = serializers.IntegerField(required=False, default=500, min_value=1, max_value=500)


class WidgetTicketsQuerySerializer(WidgetAuthSerializer):
    """Serializer for fetching tickets for a widget session."""

    status = serializers.ChoiceField(
        choices=[s.value for s in Status],
        required=False,
        allow_null=True,
        help_text="Filter by ticket status",
    )
    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=500)
    offset = serializers.IntegerField(required=False, default=0, min_value=0)


class WidgetMarkReadSerializer(WidgetAuthSerializer):
    """Serializer for marking a ticket as read."""

    pass


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


def validate_url_domain(url: str, team: Team) -> bool:
    """
    Validate that a URL's domain is in the team's widget_domains allowlist.

    Fails closed: if no allowlist is configured, returns False. This prevents an
    attacker with the public widget token from injecting an attacker-controlled
    request_url in the restore flow and having the live token emailed to it.
    """
    settings = team.conversations_settings or {}
    domains = settings.get("widget_domains") or []

    if not domains:
        return False

    parsed = urlparse(url)
    url_host = (parsed.hostname or parsed.netloc).lower()
    if not url_host:
        return False

    for domain in domains:
        domain = domain.lower().strip()
        # Accept either bare hostnames ("example.com") or full URLs
        # ("https://example.com") for consistency with validate_origin.
        if "://" in domain:
            domain = urlparse(domain).hostname or ""
        if domain.startswith("*."):
            # Wildcard: *.example.com matches sub.example.com and example.com
            base = domain[2:]
            if url_host == base or url_host.endswith("." + base):
                return True
        elif domain and url_host == domain:
            return True

    return False


def validate_url_matches_request_origin(request, url: str) -> bool:
    """
    Require `url`'s host to equal the request's Origin (or Referer) host.

    The Origin/Referer header is browser-attested and cannot be forged cross-site,
    so this binds caller-supplied URLs (e.g. the restore request_url) to the page
    that actually issued the request. Defense-in-depth on top of widget_domains:
    even if the allowlist is permissive, an attacker embedding the widget on their
    own page can't smuggle another allowed domain into request_url.

    Compares hostnames (not netlocs) so port and userinfo segments don't matter
    and can't be used to smuggle a different destination via
    `https://victim.com@attacker.example`-style URLs.
    """

    origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
    parsed_url = urlparse(url)

    # Restrict request_url scheme — exotic schemes (javascript:, data:, file:) have
    # no business in an emailed restore link.
    if parsed_url.scheme not in ("http", "https"):
        return False

    origin_host = (urlparse(origin).hostname or "").lower()
    url_host = (parsed_url.hostname or "").lower()
    if not origin_host or not url_host:
        return False
    return origin_host == url_host
