"""Self-serve partner registration for the agentic provisioning API.

Scope: HMAC and bearer partners only. Public clients (PKCE) use CIMD
auto-registration by hosting a metadata document - see
https://github.com/PostHog/posthog/pull/55299.
"""

from __future__ import annotations

import socket
import secrets
import ipaddress
from typing import Any
from urllib.parse import urlparse

import structlog
import posthoganalytics
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthApplication
from posthog.rate_limit import PartnerRegistrationIPThrottle
from posthog.utils import get_ip_address

logger = structlog.get_logger(__name__)

VALID_AUTH_METHODS = frozenset({"hmac", "bearer"})


def _is_private_ip(hostname: str) -> bool:
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved


def _validate_callback_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL format"

    if not parsed.scheme or not parsed.netloc:
        return "URL must include scheme and host"

    if parsed.scheme in OAuthApplication.DEFAULT_BLOCKED_SCHEMES:
        return f"URL scheme '{parsed.scheme}' is not allowed"

    is_loopback = parsed.hostname in ("localhost", "127.0.0.1", "::1", "[::1]")
    if not is_loopback and parsed.scheme != "https":
        return "Only https:// URLs are allowed (except localhost for development)"

    if parsed.hostname and not is_loopback and _is_private_ip(str(parsed.hostname)):
        return "Callback URL must not point to a private/internal IP address"

    if parsed.hostname and not is_loopback:
        try:
            resolved = socket.getaddrinfo(parsed.hostname, None)
        except socket.gaierror:
            return None
        for _, _, _, _, sockaddr in resolved:
            if _is_private_ip(str(sockaddr[0])):
                return "Callback URL resolves to a private/internal IP address"

    return None


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@throttle_classes([PartnerRegistrationIPThrottle])
def provisioning_register(request: Request) -> Response:
    data = request.data
    name = str(data.get("name", "")).strip()
    callback_url = str(data.get("callback_url", "")).strip()
    auth_method = str(data.get("auth_method", "")).strip()
    partner_type = str(data.get("partner_type", "")).strip()
    logo_uri = str(data.get("logo_uri", "")).strip() or None

    if not name:
        return Response({"error": "name is required"}, status=400)
    if not callback_url:
        return Response({"error": "callback_url is required"}, status=400)
    if not auth_method:
        return Response({"error": "auth_method is required"}, status=400)
    if auth_method not in VALID_AUTH_METHODS:
        return Response(
            {"error": f"auth_method must be one of: {', '.join(sorted(VALID_AUTH_METHODS))}"},
            status=400,
        )

    if (url_error := _validate_callback_url(callback_url)) is not None:
        return Response({"error": f"Invalid callback_url: {url_error}"}, status=400)

    from oauthlib.common import generate_token

    client_id = generate_token()
    client_secret = generate_token()
    signing_secret = secrets.token_hex(32) if auth_method == "hmac" else ""

    app = OAuthApplication.objects.create(
        name=name,
        client_id=client_id,
        client_secret=client_secret,
        client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
        authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        redirect_uris=callback_url,
        algorithm="RS256",
        logo_uri=logo_uri,
        provisioning_auth_method=auth_method,
        provisioning_signing_secret=signing_secret,
        provisioning_partner_type=partner_type,
        provisioning_active=False,
        provisioning_can_create_accounts=False,
        provisioning_can_provision_resources=True,
        organization=None,
        user=None,
    )

    logger.info(
        "agentic_provisioning.partner_registered",
        app_id=str(app.id),
        client_id=client_id,
        name=name,
        auth_method=auth_method,
        partner_type=partner_type,
        ip=get_ip_address(request),
    )
    try:
        posthoganalytics.capture(
            "agentic_provisioning partner_registered",
            distinct_id=f"provisioning_partner_{app.id}",
            properties={
                "auth_method": auth_method,
                "partner_type": partner_type,
                "app_id": str(app.id),
            },
        )
    except Exception:
        capture_exception()

    response_data: dict[str, Any] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "name": name,
        "auth_method": auth_method,
        "provisioning_active": False,
        "message": "Partner registered successfully. An admin must activate provisioning before you can use the API.",
    }
    if signing_secret:
        response_data["signing_secret"] = signing_secret

    return Response(response_data, status=201)
