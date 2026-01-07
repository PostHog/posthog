"""
OAuth 2.0 Dynamic Client Registration (RFC 7591)

Allows MCP clients to register themselves without prior authentication.
This is required by the MCP OAuth specification for seamless client onboarding.
"""

import time
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from oauth2_provider.models import AbstractApplication
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.oauth import OAuthApplication


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, handling proxies."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


class DCRRateLimiter:
    """Rate limiter for DCR endpoint using Django cache."""

    def __init__(
        self,
        per_ip_per_minute: int = 10,
        per_ip_per_hour: int = 100,
        global_per_hour: int = 1000,
    ):
        self.per_ip_per_minute = per_ip_per_minute
        self.per_ip_per_hour = per_ip_per_hour
        self.global_per_hour = global_per_hour

    def _get_cache_key(self, prefix: str, identifier: str, window: str) -> str:
        return f"dcr_rate_limit:{prefix}:{identifier}:{window}"

    def _get_current_window(self, seconds: int) -> str:
        return str(int(time.time()) // seconds)

    def is_rate_limited(self, ip: str) -> tuple[bool, str | None]:
        """Check if request should be rate limited. Returns (is_limited, reason)."""
        minute_window = self._get_current_window(60)
        hour_window = self._get_current_window(3600)

        # Check per-IP per-minute limit
        ip_minute_key = self._get_cache_key("ip", ip, minute_window)
        ip_minute_count = cache.get(ip_minute_key, 0)
        if ip_minute_count >= self.per_ip_per_minute:
            return True, "Too many requests. Please wait a minute."

        # Check per-IP per-hour limit
        ip_hour_key = self._get_cache_key("ip", ip, hour_window)
        ip_hour_count = cache.get(ip_hour_key, 0)
        if ip_hour_count >= self.per_ip_per_hour:
            return True, "Too many requests. Please wait an hour."

        # Check global per-hour limit
        global_hour_key = self._get_cache_key("global", "all", hour_window)
        global_hour_count = cache.get(global_hour_key, 0)
        if global_hour_count >= self.global_per_hour:
            return True, "Service temporarily unavailable. Please try again later."

        return False, None

    def _safe_incr(self, key: str, ttl: int) -> None:
        """Atomically increment a counter, creating it if needed."""
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, ttl)

    def record_request(self, ip: str) -> None:
        """Record a successful registration request."""
        minute_window = self._get_current_window(60)
        hour_window = self._get_current_window(3600)

        ip_minute_key = self._get_cache_key("ip", ip, minute_window)
        ip_hour_key = self._get_cache_key("ip", ip, hour_window)
        global_hour_key = self._get_cache_key("global", "all", hour_window)

        self._safe_incr(ip_minute_key, 60)
        self._safe_incr(ip_hour_key, 3600)
        self._safe_incr(global_hour_key, 3600)


# Global rate limiter instance
dcr_rate_limiter = DCRRateLimiter()


class DCRRequestSerializer(serializers.Serializer):
    """Validates incoming DCR requests per RFC 7591."""

    # Required fields
    redirect_uris = serializers.ListField(
        child=serializers.URLField(),
        min_length=1,
        help_text="List of allowed redirect URIs",
    )

    # Optional fields
    client_name = serializers.CharField(
        max_length=255,
        required=False,
        help_text="Human-readable name of the client",
    )
    grant_types = serializers.ListField(
        child=serializers.ChoiceField(choices=["authorization_code", "refresh_token"]),
        required=False,
        default=["authorization_code"],
        help_text="OAuth grant types the client will use",
    )
    response_types = serializers.ListField(
        child=serializers.ChoiceField(choices=["code"]),
        required=False,
        default=["code"],
        help_text="OAuth response types the client will use",
    )
    token_endpoint_auth_method = serializers.ChoiceField(
        choices=["none", "client_secret_post"],
        required=False,
        default="none",
        help_text="How the client authenticates at the token endpoint",
    )

    def validate_redirect_uris(self, value: list[str]) -> list[str]:
        """Validate redirect URIs - HTTPS required except for localhost."""
        from urllib.parse import urlparse

        from posthog.models.oauth import is_loopback_host

        for uri in value:
            parsed = urlparse(uri)

            # Custom URL schemes for native apps (RFC 8252 Section 7.1)
            is_custom_scheme = parsed.scheme not in ["http", "https", ""]

            if is_custom_scheme:
                allowed_schemes = getattr(settings, "OAUTH2_PROVIDER", {}).get(
                    "ALLOWED_REDIRECT_URI_SCHEMES", ["http", "https"]
                )
                if parsed.scheme not in allowed_schemes:
                    raise serializers.ValidationError(
                        f"Redirect URI scheme '{parsed.scheme}' is not allowed. "
                        f"Allowed schemes: {', '.join(allowed_schemes)}"
                    )
            else:
                is_loopback = is_loopback_host(parsed.hostname)
                if parsed.scheme == "http" and not is_loopback:
                    raise serializers.ValidationError(
                        f"Redirect URI {uri} must use HTTPS (HTTP only allowed for localhost)"
                    )

        return value


class DynamicClientRegistrationView(APIView):
    """
    OAuth 2.0 Dynamic Client Registration endpoint (RFC 7591).

    Allows MCP clients to register without prior authentication.
    Rate limited to prevent abuse.
    """

    permission_classes = []
    authentication_classes = []

    def post(self, request: Request) -> Response:
        # Rate limiting
        client_ip = get_client_ip(request)
        is_limited, reason = dcr_rate_limiter.is_rate_limited(client_ip)
        if is_limited:
            return Response(
                {"error": "rate_limit_exceeded", "error_description": reason},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Validate request
        serializer = DCRRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "error": "invalid_client_metadata",
                    "error_description": str(serializer.errors),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        now = timezone.now()

        # Determine client type based on auth method
        # "none" = public client (no secret), "client_secret_post" = confidential
        auth_method = data.get("token_endpoint_auth_method", "none")
        client_type = (
            AbstractApplication.CLIENT_PUBLIC if auth_method == "none" else AbstractApplication.CLIENT_CONFIDENTIAL
        )

        # Create the OAuth application
        try:
            app = OAuthApplication.objects.create(
                name=data.get("client_name", "MCP Client"),
                redirect_uris=" ".join(data["redirect_uris"]),
                client_type=client_type,
                authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
                algorithm="RS256",
                skip_authorization=False,
                # DCR-specific fields
                is_dcr_client=True,
                client_id_issued_at=now,
                # No organization or user - DCR clients are anonymous
                organization=None,
                user=None,
            )
        except Exception as e:
            return Response(
                {
                    "error": "server_error",
                    "error_description": f"Failed to create client: {e!s}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Record successful registration for rate limiting
        dcr_rate_limiter.record_request(client_ip)

        # Build response
        response_data: dict[str, Any] = {
            "client_id": str(app.client_id),
            "redirect_uris": data["redirect_uris"],
            "grant_types": data.get("grant_types", ["authorization_code"]),
            "response_types": data.get("response_types", ["code"]),
            "token_endpoint_auth_method": auth_method,
            "client_id_issued_at": int(now.timestamp()),
        }

        if data.get("client_name"):
            response_data["client_name"] = data["client_name"]

        return Response(response_data, status=status.HTTP_201_CREATED)
