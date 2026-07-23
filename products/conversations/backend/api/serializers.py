"""Serializers for Conversations API."""

from typing import Any
from urllib.parse import urlparse

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.api.utils import on_permitted_recording_domain
from posthog.models import Team
from posthog.security.url_validation import has_authority_bypass_chars

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


TRAITS_MAX_COUNT = 50
TRAIT_KEY_MAX_LENGTH = 200
TRAIT_VALUE_MAX_LENGTH = 500
SESSION_CONTEXT_MAX_FIELDS = 20
SESSION_CONTEXT_KEY_MAX_LENGTH = 100
SESSION_CONTEXT_VALUE_MAX_LENGTH = 10000


def _shorten_context_value(value: str, max_length: int) -> tuple[str, bool]:
    """Shorten an over-length value to `max_length`, returning (value, was_hard_cut).
    URLs drop their fragment first; a value still over the cap after that is hard-cut."""
    if value.startswith(("http://", "https://")) and "#" in value:
        without_fragment = value.split("#", 1)[0]
        if len(without_fragment) <= max_length:
            return without_fragment, False
        value = without_fragment
    return value[:max_length], True


class WidgetMessageSerializer(WidgetAuthSerializer):
    """Serializer for incoming widget messages."""

    distinct_id = serializers.CharField(required=False, max_length=400, help_text="PostHog distinct_id")
    message = serializers.CharField(required=True, max_length=5000, help_text="Message content")
    traits = serializers.DictField(
        required=False,
        default=dict,
        help_text="Customer traits. Oversized or malformed entries are sanitized, never rejected",
    )
    session_id = serializers.CharField(required=False, max_length=64, allow_null=True, help_text="PostHog session ID")
    session_context = serializers.DictField(
        required=False,
        default=dict,
        help_text="Session context (replay URL, current URL, etc.). Oversized values are shortened, never rejected",
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

    def validate_traits(self, value: Any) -> dict[str, str | None]:
        """Traits are attached automatically by the widget, so oversized or malformed
        entries are sanitized rather than rejected — they must never block submission."""
        if not isinstance(value, dict):
            return {}

        validated: dict[str, str | None] = {}
        for key, val in value.items():
            if len(validated) >= TRAITS_MAX_COUNT:
                break
            if not isinstance(key, str) or len(key) > TRAIT_KEY_MAX_LENGTH:
                continue

            # Only allow simple types for MVP
            if not isinstance(val, str | int | float | bool | type(None)):
                continue

            str_value = str(val) if val is not None else None
            if str_value is not None:
                str_value = str_value[:TRAIT_VALUE_MAX_LENGTH]

            validated[key] = str_value

        return validated

    def validate_session_context(self, value: Any) -> dict[str, Any]:
        """Session context is attached automatically by the widget (current URL, replay URL,
        ...), so it is sanitized rather than rejected: the customer can't shorten the page URL
        they're on, and context must never block submission. Values that are hard-cut (not
        just fragment-trimmed) get a `<key>_truncated: true` marker so consumers can flag the
        stored value as unreliable."""
        if not isinstance(value, dict):
            return {}

        validated: dict[str, Any] = {}
        truncated_keys: list[str] = []
        for key, val in value.items():
            if len(validated) >= SESSION_CONTEXT_MAX_FIELDS:
                break
            if not isinstance(key, str) or len(key) > SESSION_CONTEXT_KEY_MAX_LENGTH:
                continue

            # Allow simple types only
            if not isinstance(val, str | int | float | bool | type(None)):
                continue

            if isinstance(val, str) and len(val) > SESSION_CONTEXT_VALUE_MAX_LENGTH:
                val, was_hard_cut = _shorten_context_value(val, SESSION_CONTEXT_VALUE_MAX_LENGTH)
                if was_hard_cut:
                    truncated_keys.append(key)

            validated[key] = val

        for key in truncated_keys:
            validated[f"{key}_truncated"] = True

        return validated


class WidgetMessagesQuerySerializer(WidgetAuthSerializer):
    """Serializer for fetching messages from a ticket."""

    after = serializers.DateTimeField(required=False, allow_null=True)
    limit = serializers.IntegerField(required=False, default=500, min_value=1, max_value=500)


WIDGET_TICKETS_DEFAULT_LIMIT = 100


class WidgetTicketsQuerySerializer(WidgetAuthSerializer):
    """Serializer for fetching tickets for a widget session."""

    status = serializers.ChoiceField(
        choices=[s.value for s in Status],
        required=False,
        allow_null=True,
        help_text="Filter by ticket status",
    )
    limit = serializers.IntegerField(required=False, default=WIDGET_TICKETS_DEFAULT_LIMIT, min_value=1, max_value=500)
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

    if has_authority_bypass_chars(url):
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

    if has_authority_bypass_chars(url):
        return False

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
