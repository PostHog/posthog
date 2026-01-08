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
from django.utils import timezone

import structlog
from oauth2_provider.models import AbstractApplication
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.oauth import OAuthApplication
from posthog.rate_limit import IPThrottle

logger = structlog.get_logger(__name__)


class DCRBurstThrottle(IPThrottle):
    """Rate limit DCR by IP - burst limit."""

    scope = "dcr_burst"
    rate = "10/minute"


class DCRSustainedThrottle(IPThrottle):
    """Rate limit DCR by IP - sustained limit."""

    scope = "dcr_sustained"
    rate = "100/hour"


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
        choices=["none"],
        required=False,
        default="none",
        help_text="How the client authenticates at the token endpoint (only 'none' supported for public clients)",
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

        # Create the OAuth application
        # Model's clean() validates redirect URIs (HTTPS, loopback, custom schemes)
        try:
            app = OAuthApplication.objects.create(
                name=data.get("client_name", "MCP Client"),
                redirect_uris=" ".join(data["redirect_uris"]),
                client_type=AbstractApplication.CLIENT_PUBLIC,
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
        except ValidationError as e:
            # Convert Django ValidationError to RFC 7591 error format
            if hasattr(e, "message_dict"):
                error_detail = "; ".join(f"{k}: {', '.join(v)}" for k, v in e.message_dict.items())
            else:
                error_detail = "; ".join(e.messages)
            return Response(
                {
                    "error": "invalid_redirect_uri",
                    "error_description": error_detail,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            logger.exception("dcr_client_creation_failed")
            return Response(
                {
                    "error": "server_error",
                    "error_description": "Failed to create client",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
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

        if data.get("client_name"):
            response_data["client_name"] = data["client_name"]

        return Response(response_data, status=status.HTTP_201_CREATED)
