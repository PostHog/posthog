"""
OAuth 2.0 Dynamic Client Registration (RFC 7591)

Allows MCP clients to register themselves without prior authentication.
This is required by the MCP OAuth specification for seamless client onboarding.

Note: We only support PUBLIC clients (token_endpoint_auth_method: "none").
MCP clients run on user devices and cannot securely store a client_secret.
Security is provided by PKCE (required for all OAuth flows).
"""

from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils import timezone

import structlog
from oauth2_provider.models import AbstractApplication
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthApplication
from posthog.rate_limit import IPThrottle

logger = structlog.get_logger(__name__)

# Blocked words in client names to prevent confusion attacks
# These prevent malicious apps from impersonating official PostHog applications
BLOCKED_CLIENT_NAME_PREFIXES = ["posthog"]  # Block names starting with these
BLOCKED_CLIENT_NAME_WORDS = ["official", "verified", "trusted"]  # Block names containing these


def validate_client_name(value: str) -> None:
    """Validate that client name doesn't impersonate official apps."""
    lower_value = value.lower()
    for prefix in BLOCKED_CLIENT_NAME_PREFIXES:
        if lower_value.startswith(prefix):
            raise serializers.ValidationError(f"Client name cannot start with '{prefix}'")
    for word in BLOCKED_CLIENT_NAME_WORDS:
        if word in lower_value:
            raise serializers.ValidationError(f"Client name cannot contain '{word}'")


# Known partner patterns for deriving partner_id from client_name
# Format: (pattern_substring, partner_id)
KNOWN_PARTNER_PATTERNS: list[tuple[str, str]] = [
    ("replit", "replit"),
    ("claude code", "claude-code"),
    ("claude-code", "claude-code"),
    ("claudecode", "claude-code"),
    ("cursor", "cursor"),
    ("windsurf", "windsurf"),
    ("zed", "zed"),
    ("vscode", "vscode"),
    ("visual studio code", "vscode"),
    ("vs code", "vscode"),
    ("cline", "cline"),
    ("continue", "continue"),
    ("cody", "cody"),
    ("roo", "roo"),
    ("roocode", "roo"),
]


def derive_software_id_from_name(client_name: str | None) -> str | None:
    """Derive software_id from client_name by matching known patterns."""
    if not client_name:
        return None
    lower_name = client_name.lower()
    for pattern, software_id in KNOWN_PARTNER_PATTERNS:
        if pattern in lower_name:
            return software_id
    return None


class DCRBurstThrottle(IPThrottle):
    """Rate limit DCR by IP - burst limit."""

    scope = "dcr_burst"
    rate = "60/minute"


class DCRSustainedThrottle(IPThrottle):
    """Rate limit DCR by IP - sustained limit."""

    scope = "dcr_sustained"
    rate = "1000/hour"


class DCRRequestSerializer(serializers.Serializer):
    """Validates incoming DCR requests per RFC 7591."""

    # Required fields
    # Use CharField instead of URLField to allow custom URI schemes (e.g., myapp://callback)
    # per RFC 8252 Section 7.1. The OAuthApplication model's clean() method handles full validation.
    # Whitespace is rejected to prevent redirect URI injection (URIs are stored space-separated).
    redirect_uris = serializers.ListField(
        child=serializers.CharField(
            validators=[RegexValidator(regex=r"^\S+$", message="Redirect URI cannot contain whitespace")]
        ),
        min_length=1,
        help_text="List of allowed redirect URIs",
    )

    # Optional fields
    client_name = serializers.CharField(
        max_length=255,
        required=False,
        help_text="Human-readable name of the client",
        validators=[validate_client_name],
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
        choices=["none"],
        required=False,
        default="none",
        help_text="How the client authenticates at the token endpoint (only 'none' supported for public clients)",
    )
    # Software identification per RFC 7591 for grouping clients by integration source
    software_id = serializers.CharField(
        max_length=100,
        required=False,
        help_text="Identifier for the software registering this client per RFC 7591 (e.g., 'replit', 'claude-code')",
    )


class DynamicClientRegistrationView(APIView):
    """
    OAuth 2.0 Dynamic Client Registration endpoint (RFC 7591).

    Allows MCP clients to register without prior authentication.
    Rate limited to prevent abuse.
    """

    permission_classes = []
    authentication_classes = []
    throttle_classes = [DCRBurstThrottle, DCRSustainedThrottle]

    def post(self, request: Request) -> Response:
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

        # Determine software_id: use provided value or derive from client_name
        client_name = data.get("client_name")
        software_id = data.get("software_id") or derive_software_id_from_name(client_name)

        # Create the OAuth application
        # Model's clean() validates redirect URIs (HTTPS, loopback, custom schemes)
        try:
            app = OAuthApplication.objects.create(
                name=client_name or "MCP Client",
                redirect_uris=" ".join(data["redirect_uris"]),
                client_type=AbstractApplication.CLIENT_PUBLIC,
                authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
                algorithm="RS256",
                skip_authorization=False,
                # DCR-specific fields
                is_dcr_client=True,
                dcr_client_id_issued_at=now,
                software_id=software_id,
                # No organization or user - DCR clients are anonymous
                organization=None,
                user=None,
            )
        except ValidationError as e:
            # Only expose redirect_uri validation errors to clients
            # Other validation errors (like missing RSA key) are internal and should not be leaked
            if hasattr(e, "message_dict") and "redirect_uris" in e.message_dict:
                error_detail = "; ".join(e.message_dict["redirect_uris"])
                return Response(
                    {
                        "error": "invalid_redirect_uri",
                        "error_description": error_detail,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Log internal validation errors but don't expose details
            logger.exception("dcr_validation_failed")
            capture_exception(e)
            return Response(
                {
                    "error": "server_error",
                    "error_description": "Failed to create client",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as e:
            logger.exception("dcr_client_creation_failed")
            capture_exception(e)
            return Response(
                {
                    "error": "server_error",
                    "error_description": "Failed to create client",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Log successful registration for analytics
        logger.info(
            "dcr_client_registered",
            client_id=str(app.client_id),
            software_id=software_id,
            client_name=client_name,
            redirect_uri_count=len(data["redirect_uris"]),
        )

        # Build response
        response_data: dict[str, Any] = {
            "client_id": str(app.client_id),
            "redirect_uris": data["redirect_uris"],
            "grant_types": data.get("grant_types", ["authorization_code"]),
            "response_types": data.get("response_types", ["code"]),
            "token_endpoint_auth_method": "none",
            "client_id_issued_at": int(now.timestamp()),
        }

        if client_name:
            response_data["client_name"] = client_name

        if software_id:
            response_data["software_id"] = software_id

        return Response(response_data, status=status.HTTP_201_CREATED)
