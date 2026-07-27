"""
OAuth 2.0 Dynamic Client Registration (RFC 7591)

Allows MCP clients to register themselves without prior authentication.
This is required by the MCP OAuth specification for seamless client onboarding.

Supports both public clients (token_endpoint_auth_method: "none") and
confidential clients (token_endpoint_auth_method: "client_secret_post").
Public clients rely on PKCE for security. Confidential clients (e.g. claude.ai)
can securely store a client_secret server-side.
"""

from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils import timezone

import structlog
import posthoganalytics
from oauth2_provider.generators import generate_client_secret
from oauth2_provider.models import AbstractApplication
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthApplication
from posthog.rate_limit import IPThrottle
from posthog.scopes import filter_to_unprivileged_scopes

from .client_name import sanitize_client_name, validate_client_name

logger = structlog.get_logger(__name__)


def filter_dcr_scopes(scope: str) -> list[str]:
    """Parse an RFC 7591 space-delimited `scope` string into the deduped, allow-listed
    scopes a DCR client may register. See `filter_to_unprivileged_scopes` for the rule."""
    return filter_to_unprivileged_scopes(scope.split())


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
        choices=["none", "client_secret_post"],
        required=False,
        default="none",
        help_text="How the client authenticates at the token endpoint: 'none' for public clients, 'client_secret_post' for confidential clients",
    )
    scope = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Space-delimited OAuth scopes (RFC 7591). Sets the client's scope ceiling; privileged scopes are stripped, and a set that strips to nothing is rejected. Omit to use the default scope set.",
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

        client_name = sanitize_client_name(data["client_name"]) if data.get("client_name") else "MCP Client"
        is_confidential = data.get("token_endpoint_auth_method") == "client_secret_post"
        client_type = AbstractApplication.CLIENT_CONFIDENTIAL if is_confidential else AbstractApplication.CLIENT_PUBLIC

        # Generate the secret before create() so we can return the plaintext
        # for confidential clients. The model's ClientSecretField.pre_save()
        # hashes it automatically on save. Public clients also get a secret
        # (via the model default) but we generate it explicitly here to keep
        # the create() call simple -- we just don't return it in the response.
        plaintext_secret = generate_client_secret()

        requested_scope = data.get("scope")
        app_scopes = filter_dcr_scopes(requested_scope) if requested_scope else []

        # A non-empty `scope` that filters to nothing means the client asked only for
        # scopes it can't self-register (privileged/internal/hidden/unknown). Reject
        # rather than store an empty ceiling: an empty ceiling resolves to the broad
        # default at /authorize, so silently accepting would widen the client beyond
        # what it requested. Absent / "" / null `scope` is the legitimate "use default"
        # path and falls through to an empty ceiling below.
        if requested_scope and not app_scopes:
            return Response(
                {
                    "error": "invalid_client_metadata",
                    "error_description": "None of the requested scopes are available to self-registered clients. Omit `scope` to register with the default scope set.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            app = OAuthApplication.objects.create(
                name=client_name,
                redirect_uris=" ".join(data["redirect_uris"]),
                client_type=client_type,
                client_secret=plaintext_secret,
                authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
                algorithm="RS256",
                skip_authorization=False,
                is_dcr_client=True,
                dcr_client_id_issued_at=now,
                scopes=app_scopes,
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

        posthoganalytics.capture(
            distinct_id=str(app.client_id),
            event="dcr_application_created",
            properties={
                "client_name": client_name,
                "app_id": str(app.pk),
                "client_type": "confidential" if is_confidential else "public",
                "redirect_uris_count": len(data["redirect_uris"]),
            },
        )

        auth_method = data.get("token_endpoint_auth_method", "none")

        # Build response per RFC 7591 Section 3.2
        response_data: dict[str, Any] = {
            "client_id": str(app.client_id),
            "redirect_uris": data["redirect_uris"],
            "grant_types": data.get("grant_types", ["authorization_code"]),
            "response_types": data.get("response_types", ["code"]),
            "token_endpoint_auth_method": auth_method,
            "client_id_issued_at": int(now.timestamp()),
        }

        if is_confidential:
            response_data["client_secret"] = plaintext_secret
            response_data["client_secret_expires_at"] = 0  # 0 = never expires per RFC 7591

        if data.get("client_name"):
            response_data["client_name"] = client_name

        # RFC 7591 Section 3.2.1: when the server modifies requested scopes, it
        # returns the registered `scope` so the client sees the privileged-strip.
        if app_scopes:
            response_data["scope"] = " ".join(app_scopes)

        return Response(response_data, status=status.HTTP_201_CREATED)
