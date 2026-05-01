"""Self-serve partner registration for the agentic provisioning API.

Scope: HMAC partners only - webhook-driven server-to-server integrations
(like Stripe) that sign requests with a shared secret. Public clients
(PKCE: wizard, Replit, vibe coding platforms) use CIMD auto-registration
by hosting a metadata document instead - see
https://github.com/PostHog/posthog/pull/55299.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlparse

from django.core.exceptions import ValidationError as DjangoValidationError

import structlog
import posthoganalytics
from drf_spectacular.utils import OpenApiResponse
from oauthlib.common import generate_token
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.cloud_utils import is_dev_mode
from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthApplication
from posthog.rate_limit import PartnerRegistrationIPThrottle
from posthog.security.url_validation import is_url_allowed
from posthog.utils import get_ip_address

logger = structlog.get_logger(__name__)

NAME_MAX_LENGTH = 100
PARTNER_TYPE_MAX_LENGTH = 50
SIGNING_SECRET_BYTES = 32
ALLOWED_URL_SCHEMES = frozenset(["https"])
DEV_ALLOWED_URL_SCHEMES = frozenset(["http", "https"])
DEFAULT_PROVISIONING_ACTIVE = False
DEFAULT_CAN_CREATE_ACCOUNTS = False
DEFAULT_CAN_PROVISION_RESOURCES = True


def _validate_callback_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL format"

    if not parsed.scheme or not parsed.netloc:
        return "URL must include scheme and host"

    if parsed.scheme in OAuthApplication.DEFAULT_BLOCKED_SCHEMES:
        return f"URL scheme '{parsed.scheme}' is not allowed"

    allowed_schemes = DEV_ALLOWED_URL_SCHEMES if is_dev_mode() else ALLOWED_URL_SCHEMES
    if parsed.scheme not in allowed_schemes:
        return f"URL must use HTTPS (got '{parsed.scheme}')"

    allowed, reason = is_url_allowed(url)
    if not allowed:
        return reason

    return None


class ProvisioningRegisterRequestSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=NAME_MAX_LENGTH,
        help_text="Display name shown to end users when they authorize the partner.",
    )
    callback_url = serializers.CharField(
        help_text=(
            "OAuth redirect URI. Must be an HTTPS URL with a public host - private IPs, "
            "loopback, cloud metadata endpoints, and non-HTTPS schemes are rejected."
        ),
    )
    partner_type = serializers.CharField(
        max_length=PARTNER_TYPE_MAX_LENGTH,
        required=False,
        allow_blank=True,
        default="",
        help_text="Free-form partner category for analytics (e.g. 'billing', 'wizard').",
    )
    logo_uri = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        help_text="HTTPS URL to a square logo shown on the consent screen. Same scheme and host rules as callback_url.",
    )

    def validate_callback_url(self, value: str) -> str:
        error = _validate_callback_url(value)
        if error is not None:
            raise serializers.ValidationError(error)
        return value

    def validate_logo_uri(self, value: str | None) -> str | None:
        if not value:
            return None
        error = _validate_callback_url(value)
        if error is not None:
            raise serializers.ValidationError(error)
        return value


class ProvisioningRegisterResponseSerializer(serializers.Serializer):
    client_id = serializers.CharField(help_text="OAuth client identifier issued to the partner.")
    client_secret = serializers.CharField(
        help_text="OAuth client secret. Returned once at registration; store securely.",
    )
    signing_secret = serializers.CharField(
        help_text="HMAC signing secret used to authenticate webhook requests from the partner.",
    )
    name = serializers.CharField(help_text="Echo of the registered partner name.")
    provisioning_active = serializers.BooleanField(
        help_text=(
            "Whether the partner can use the provisioning API. Always false on registration; "
            "an admin must activate the partner before any provisioning calls succeed."
        ),
    )
    message = serializers.CharField(help_text="Human-readable summary of the registration result.")


class ProvisioningRegisterView(APIView):
    authentication_classes: list = []
    permission_classes: list = []
    throttle_classes = [PartnerRegistrationIPThrottle]

    @validated_request(
        request_serializer=ProvisioningRegisterRequestSerializer,
        responses={
            201: OpenApiResponse(response=ProvisioningRegisterResponseSerializer),
        },
        summary="Register a self-serve HMAC partner",
        tags=["agentic_provisioning"],
    )
    def post(self, request: ValidatedRequest) -> Response:
        data = request.validated_data
        name = data["name"].strip()
        callback_url = data["callback_url"].strip()
        partner_type = (data.get("partner_type") or "").strip()
        logo_uri = data.get("logo_uri") or None

        client_id = generate_token()
        client_secret = generate_token()
        signing_secret = secrets.token_hex(SIGNING_SECRET_BYTES)

        try:
            app = OAuthApplication.objects.create(
                name=name,
                client_id=client_id,
                client_secret=client_secret,
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris=callback_url,
                algorithm="RS256",
                logo_uri=logo_uri,
                provisioning_auth_method="hmac",
                provisioning_signing_secret=signing_secret,
                provisioning_partner_type=partner_type,
                provisioning_active=DEFAULT_PROVISIONING_ACTIVE,
                provisioning_can_create_accounts=DEFAULT_CAN_CREATE_ACCOUNTS,
                provisioning_can_provision_resources=DEFAULT_CAN_PROVISION_RESOURCES,
                organization=None,
                user=None,
            )
        except DjangoValidationError as e:
            raise serializers.ValidationError("; ".join(e.messages) if e.messages else "Invalid registration")

        logger.info(
            "agentic_provisioning.partner_registered",
            app_id=str(app.id),
            client_id=client_id,
            name=name,
            partner_type=partner_type,
            ip=get_ip_address(request),
        )
        try:
            posthoganalytics.capture(
                "agentic_provisioning partner_registered",
                distinct_id=f"provisioning_partner_{app.id}",
                properties={
                    "partner_type": partner_type,
                    "app_id": str(app.id),
                },
            )
        except Exception:
            capture_exception()

        response_serializer = ProvisioningRegisterResponseSerializer(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "signing_secret": signing_secret,
                "name": name,
                "provisioning_active": DEFAULT_PROVISIONING_ACTIVE,
                "message": (
                    "Partner registered successfully. An admin must activate provisioning before you can use the API."
                ),
            }
        )
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
