"""Self-serve partner registration for the agentic provisioning API.

Scope: HMAC partners only - webhook-driven server-to-server integrations
(like Stripe) that sign requests with a shared secret. Public clients
(PKCE: wizard, Replit, vibe coding platforms) use CIMD auto-registration
by hosting a metadata document instead - see
https://github.com/PostHog/posthog/pull/55299.
"""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlparse

from django.core.exceptions import ValidationError

import structlog
import posthoganalytics
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthApplication
from posthog.rate_limit import PartnerRegistrationIPThrottle
from posthog.security.url_validation import is_url_allowed
from posthog.utils import get_ip_address

logger = structlog.get_logger(__name__)

NAME_MAX_LENGTH = 100
PARTNER_TYPE_MAX_LENGTH = 50


def _validate_callback_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL format"

    if not parsed.scheme or not parsed.netloc:
        return "URL must include scheme and host"

    if parsed.scheme in OAuthApplication.DEFAULT_BLOCKED_SCHEMES:
        return f"URL scheme '{parsed.scheme}' is not allowed"

    allowed, reason = is_url_allowed(url)
    if not allowed:
        return reason

    return None


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@throttle_classes([PartnerRegistrationIPThrottle])
def provisioning_register(request: Request) -> Response:
    data = request.data
    name = str(data.get("name", "")).strip()
    callback_url = str(data.get("callback_url", "")).strip()
    partner_type = str(data.get("partner_type", "")).strip()
    logo_uri = str(data.get("logo_uri", "")).strip() or None

    if not name:
        return Response({"error": "name is required"}, status=400)
    if len(name) > NAME_MAX_LENGTH:
        return Response({"error": f"name must be {NAME_MAX_LENGTH} characters or fewer"}, status=400)
    if not callback_url:
        return Response({"error": "callback_url is required"}, status=400)
    if len(partner_type) > PARTNER_TYPE_MAX_LENGTH:
        return Response(
            {"error": f"partner_type must be {PARTNER_TYPE_MAX_LENGTH} characters or fewer"},
            status=400,
        )

    if (url_error := _validate_callback_url(callback_url)) is not None:
        return Response({"error": f"Invalid callback_url: {url_error}"}, status=400)

    from oauthlib.common import generate_token

    client_id = generate_token()
    client_secret = generate_token()
    signing_secret = secrets.token_hex(32)

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
            provisioning_active=False,
            provisioning_can_create_accounts=False,
            provisioning_can_provision_resources=True,
            organization=None,
            user=None,
        )
    except ValidationError as e:
        return Response({"error": "; ".join(e.messages) if e.messages else "Invalid registration"}, status=400)

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

    response_data: dict[str, Any] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "signing_secret": signing_secret,
        "name": name,
        "provisioning_active": False,
        "message": "Partner registered successfully. An admin must activate provisioning before you can use the API.",
    }
    return Response(response_data, status=201)
