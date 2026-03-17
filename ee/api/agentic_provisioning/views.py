from __future__ import annotations

import time
import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import IntegrityError
from django.http import HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.utils import timezone

import requests
import structlog
import posthoganalytics
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import StripeIntegration
from posthog.models.oauth import OAuthAccessToken, OAuthRefreshToken, find_oauth_refresh_token
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_oauth_access_token, generate_random_oauth_refresh_token
from posthog.utils import get_instance_region

from ee.settings import BILLING_SERVICE_URL

from . import AUTH_CODE_CACHE_PREFIX, PENDING_AUTH_CACHE_PREFIX, RESOURCE_SERVICE_CACHE_PREFIX
from .region_proxy import stripe_region_proxy
from .signature import SUPPORTED_VERSIONS, verify_api_version, verify_stripe_signature

logger = structlog.get_logger(__name__)

AUTH_CODE_TTL_SECONDS = 300
PENDING_AUTH_TTL_SECONDS = 600
DEEP_LINK_TTL_SECONDS = 600
DEEP_LINK_CACHE_PREFIX = "stripe_app_deep_link:"
SUPPORTED_DEEP_LINK_PURPOSES = {"dashboard"}
DEEP_LINK_RATE_LIMIT_PREFIX = "agentic_login_rate:"
DEEP_LINK_RATE_LIMIT_MAX_ATTEMPTS = 10
DEEP_LINK_RATE_LIMIT_WINDOW_SECONDS = 300

STRIPE_APP_NAME = "PostHog Stripe App"

ACCESS_TOKEN_EXPIRY_SECONDS = 365 * 24 * 3600


# ---------------------------------------------------------------------------
# Service catalog — a parent "posthog" service with component children per
# product. Users provision "posthog" and get all products; individual products
# use component pricing with their Stripe price IDs so the orchestrator can
# display pricing info.
# ---------------------------------------------------------------------------

SERVICES_CACHE_KEY = "agentic_provisioning:services"
SERVICES_CACHE_TTL = 3600  # 1 hour
SERVICES_CACHE_RETRY_TTL = 300  # 5 min retry window when billing is down

# Products that shouldn't be listed as provisionable services
_EXCLUDED_PRODUCT_TYPES = {"platform_and_support", "integrations"}

# Billing product type -> APP service categories
_CATEGORY_MAP: dict[str, list[str]] = {
    "product_analytics": ["analytics"],
    "session_replay": ["observability"],
    "feature_flags": ["feature_flags"],
    "surveys": ["analytics"],
    "data_warehouse": ["database"],
    "error_tracking": ["observability"],
    "llm_analytics": ["analytics", "ai"],
    "logs": ["observability"],
    "posthog_ai": ["ai"],
    "realtime_destinations": ["messaging"],
    "workflows_emails": ["email"],
}

POSTHOG_SERVICE_ID = "posthog"

POSTHOG_PARENT_SERVICE: dict[str, Any] = {
    "id": POSTHOG_SERVICE_ID,
    "description": "PostHog — product analytics, session replay, feature flags, A/B testing, surveys, and more",
    "categories": ["analytics", "observability", "feature_flags", "ai"],
    "pricing": {"type": "free"},
}


def _fetch_services_from_billing() -> list[dict[str, Any]] | None:
    """Fetch product catalog from billing. Returns None on failure."""
    try:
        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/products-v2",
            params={"plan": "standard"},
        )
        res.raise_for_status()
        products = res.json().get("products", [])
    except Exception:
        logger.exception("agentic_provisioning.services.billing_fetch_failed")
        return None

    services: list[dict[str, Any]] = [POSTHOG_PARENT_SERVICE]
    for product in products:
        product_type = product.get("type", "")
        if product_type in _EXCLUDED_PRODUCT_TYPES:
            continue
        if product.get("inclusion_only"):
            continue

        paid_plan = next((p for p in product.get("plans", []) if p.get("price_id")), None)
        if not paid_plan:
            continue

        services.append(
            {
                "id": product_type,
                "description": product.get("headline") or product.get("description", ""),
                "categories": _CATEGORY_MAP.get(product_type, ["analytics"]),
                "pricing": {
                    "type": "component",
                    "component": {
                        "options": [
                            {
                                "parent_service_ids": [POSTHOG_SERVICE_ID],
                                "type": "paid",
                                "paid": {
                                    "type": "stripe_price",
                                    "stripe_price": paid_plan["price_id"],
                                },
                            }
                        ]
                    },
                },
            }
        )

    return services


SERVICES_CACHE_EXPIRES_KEY = "agentic_provisioning:services:expires_at"
SERVICES_CACHE_STORE_TTL = 86400  # store data for 24h so stale reads work


def _get_services() -> list[dict[str, Any]]:
    cached = cache.get(SERVICES_CACHE_KEY)
    expires_at = cache.get(SERVICES_CACHE_EXPIRES_KEY)

    now = time.time()
    if cached is not None and expires_at is not None and now < expires_at:
        return cached

    services = _fetch_services_from_billing()
    if services is not None:
        cache.set(SERVICES_CACHE_KEY, services, SERVICES_CACHE_STORE_TTL)
        cache.set(SERVICES_CACHE_EXPIRES_KEY, now + SERVICES_CACHE_TTL, SERVICES_CACHE_STORE_TTL)
        return services

    # Billing failed — serve stale data, retry after SERVICES_CACHE_RETRY_TTL
    if cached is not None:
        logger.warning("agentic_provisioning.services.serving_stale_cache")
        cache.set(SERVICES_CACHE_EXPIRES_KEY, now + SERVICES_CACHE_RETRY_TTL, SERVICES_CACHE_STORE_TTL)
        return cached

    logger.warning("agentic_provisioning.services.no_cache_fallback")
    fallback = [POSTHOG_PARENT_SERVICE]
    cache.set(SERVICES_CACHE_KEY, fallback, SERVICES_CACHE_RETRY_TTL)
    cache.set(SERVICES_CACHE_EXPIRES_KEY, now + SERVICES_CACHE_RETRY_TTL, SERVICES_CACHE_RETRY_TTL)
    return fallback


VALID_SERVICE_IDS: set[str] = {POSTHOG_SERVICE_ID} | set(_CATEGORY_MAP.keys())


# ---------------------------------------------------------------------------
# GET /provisioning/health — liveness probe, returns supported protocol versions
# ---------------------------------------------------------------------------


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def provisioning_health(request: Request) -> Response:
    error = verify_stripe_signature(request)
    if error:
        return error
    if error := verify_api_version(request):
        return error

    return Response({"supported_versions": SUPPORTED_VERSIONS, "status": "ok"})


# ---------------------------------------------------------------------------
# GET /provisioning/services — returns the catalog of provisionable services
# ---------------------------------------------------------------------------


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def provisioning_services(request: Request) -> Response:
    error = verify_stripe_signature(request)
    if error:
        return error
    if error := verify_api_version(request):
        return error

    return Response({"data": _get_services(), "next_cursor": ""})


# ---------------------------------------------------------------------------
# POST /provisioning/account_requests — onboard a new or existing user and
# return either an auth code (new user) or a redirect URL (existing user)
# ---------------------------------------------------------------------------


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@stripe_region_proxy(strategy="body_region")
def account_requests(request: Request) -> Response:
    if error := verify_api_version(request):
        return error

    data = request.data
    request_id = data.get("id", "")
    email = data.get("email")
    if not email:
        return Response(
            {"type": "error", "error": {"code": "invalid_request", "message": "email is required"}}, status=400
        )

    scopes = data.get("scopes", [])
    confirmation_secret = data.get("confirmation_secret", "")
    expires_at_str = data.get("expires_at", "")
    configuration = data.get("configuration") or {}
    orchestrator = data.get("orchestrator") or {}

    if expires_at_str:
        from django.utils.dateparse import parse_datetime

        expires_at = parse_datetime(expires_at_str)
        if expires_at and expires_at < timezone.now():
            return Response(
                {"type": "error", "error": {"code": "expired", "message": "Account request has expired"}},
                status=400,
            )

    stripe_info = orchestrator.get("stripe") or {}
    stripe_account_id = stripe_info.get("account", "") if orchestrator.get("type") == "stripe" else ""
    if not stripe_account_id:
        return Response(
            {
                "type": "error",
                "error": {"code": "invalid_request", "message": "orchestrator.stripe.account is required"},
            },
            status=400,
        )

    region = (configuration.get("region") or "US").upper()

    existing_user = User.objects.filter(email=email).first()

    if existing_user:
        return _handle_existing_user(request_id, existing_user, confirmation_secret, scopes, stripe_account_id, region)

    return _handle_new_user(request_id, data, email, scopes, stripe_account_id, region)


def _handle_existing_user(
    request_id: str,
    user: User,
    confirmation_secret: str,
    scopes: list[str],
    stripe_account_id: str = "",
    region: str = "US",
) -> Response:
    cache.set(
        f"{PENDING_AUTH_CACHE_PREFIX}{confirmation_secret}",
        {
            "email": user.email,
            "scopes": scopes,
            "stripe_account_id": stripe_account_id,
            "region": region,
        },
        timeout=PENDING_AUTH_TTL_SECONDS,
    )

    authorize_url = _build_authorize_url(confirmation_secret, scopes)
    return Response(
        {
            "id": request_id,
            "type": "requires_auth",
            "requires_auth": {
                "type": "redirect",
                "redirect": {"url": authorize_url},
            },
        }
    )


def _handle_new_user(
    request_id: str,
    data: dict,
    email: str,
    scopes: list[str],
    stripe_account_id: str,
    region: str,
) -> Response:
    name = data.get("name", "")
    first_name = name.split(" ")[0] if name else ""

    try:
        organization, team, user = User.objects.bootstrap(
            organization_name=f"Stripe ({email})",
            email=email,
            password=None,
            first_name=first_name,
        )
    except IntegrityError:
        existing = User.objects.filter(email=email).first()
        if existing:
            return _handle_existing_user(
                request_id, existing, data.get("confirmation_secret", ""), scopes, stripe_account_id, region
            )
        return Response(
            {
                "id": request_id,
                "type": "error",
                "error": {"code": "account_creation_failed", "message": "Failed to create account"},
            },
            status=500,
        )

    code = secrets.token_urlsafe(32)
    cache_key = f"{AUTH_CODE_CACHE_PREFIX}{code}"
    cache.set(
        cache_key,
        {
            "user_id": user.id,
            "org_id": str(organization.id),
            "team_id": team.id,
            "stripe_account_id": stripe_account_id,
            "scopes": scopes,
            "region": region,
        },
        timeout=AUTH_CODE_TTL_SECONDS,
    )

    return Response({"id": request_id, "type": "oauth", "oauth": {"code": code}})


def _build_authorize_url(confirmation_secret: str, scopes: list[str]) -> str:
    base = settings.SITE_URL.rstrip("/")
    params = urlencode({"state": confirmation_secret, "scope": " ".join(scopes)})
    return f"{base}/api/agentic/authorize?{params}"


# ---------------------------------------------------------------------------
# GET /api/agentic/authorize
# Interactive OAuth consent for existing users (APP 0.1d §A1 "requires_auth").
# The orchestrator redirects the user here; on approval we issue an auth code
# and redirect back to the orchestrator callback.
# ---------------------------------------------------------------------------


@login_required
def agentic_authorize(request: Any) -> HttpResponseBase:
    state = request.GET.get("state", "")
    if not state:
        return HttpResponseRedirect(f"{settings.SITE_URL}?error=missing_state")

    pending_key = f"{PENDING_AUTH_CACHE_PREFIX}{state}"
    pending = cache.get(pending_key)
    if pending is None:
        return HttpResponseRedirect(f"{settings.SITE_URL}?error=expired_or_invalid_state")

    if request.user.email != pending["email"]:
        return HttpResponseRedirect(f"{settings.SITE_URL}?error=email_mismatch")

    cache.delete(pending_key)

    user = request.user
    membership = user.organization_memberships.first()
    if not membership:
        return HttpResponseRedirect(f"{settings.SITE_URL}?error=no_organization")

    organization = membership.organization
    team = organization.teams.filter(is_demo=False).first() or organization.teams.first()
    if not team:
        return HttpResponseRedirect(f"{settings.SITE_URL}?error=no_team")

    code = secrets.token_urlsafe(32)
    cache.set(
        f"{AUTH_CODE_CACHE_PREFIX}{code}",
        {
            "user_id": user.id,
            "org_id": str(organization.id),
            "team_id": team.id,
            "stripe_account_id": pending.get("stripe_account_id", ""),
            "scopes": pending.get("scopes", []),
            "region": pending.get("region", "US"),
        },
        timeout=AUTH_CODE_TTL_SECONDS,
    )

    callback_url = settings.STRIPE_ORCHESTRATOR_CALLBACK_URL
    params = urlencode({"code": code, "state": state})
    return HttpResponseRedirect(f"{callback_url}?{params}")


# ---------------------------------------------------------------------------
# POST /oauth/token — exchange auth codes or refresh tokens for access tokens
# ---------------------------------------------------------------------------


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@stripe_region_proxy(strategy="token_lookup")
def oauth_token(request: Request) -> Response:
    grant_type = request.data.get("grant_type", "")

    if grant_type == "authorization_code":
        return _exchange_authorization_code(request)
    elif grant_type == "refresh_token":
        return _exchange_refresh_token(request)
    else:
        return Response(
            {"error": "unsupported_grant_type", "error_description": f"Unsupported grant_type: {grant_type}"},
            status=400,
        )


def _exchange_authorization_code(request: Request) -> Response:
    code = request.data.get("code", "")
    if not code:
        return Response({"error": "invalid_request", "error_description": "code is required"}, status=400)

    cache_key = f"{AUTH_CODE_CACHE_PREFIX}{code}"
    code_data = cache.get(cache_key)
    if code_data is None:
        return Response(
            {"error": "invalid_grant", "error_description": "Invalid or expired authorization code"}, status=400
        )

    cache.delete(cache_key)

    user_id = code_data["user_id"]
    team_id = code_data["team_id"]
    scopes = code_data.get("scopes", [])

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({"error": "invalid_grant", "error_description": "User not found"}, status=400)

    oauth_app = _get_stripe_oauth_app()
    scope_str = " ".join(scopes) if scopes else StripeIntegration.SCOPES

    access_token_value = generate_random_oauth_access_token(None)
    access_token = OAuthAccessToken.objects.create(
        application=oauth_app,
        token=access_token_value,
        user=user,
        expires=timezone.now() + timedelta(seconds=ACCESS_TOKEN_EXPIRY_SECONDS),
        scope=scope_str,
        scoped_teams=[team_id],
    )

    refresh_token_value = generate_random_oauth_refresh_token(None)
    OAuthRefreshToken.objects.create(
        application=oauth_app,
        token=refresh_token_value,
        user=user,
        access_token=access_token,
        scoped_teams=[team_id],
    )

    account_id = str(code_data.get("org_id", ""))

    return Response(
        {
            "token_type": "bearer",
            "access_token": access_token_value,
            "refresh_token": refresh_token_value,
            "expires_in": ACCESS_TOKEN_EXPIRY_SECONDS,
            "account": {
                "id": account_id,
                "payment_credentials": "provider",
            },
        }
    )


def _exchange_refresh_token(request: Request) -> Response:
    refresh_token_value = request.data.get("refresh_token", "")
    if not refresh_token_value:
        return Response({"error": "invalid_request", "error_description": "refresh_token is required"}, status=400)

    old_refresh = find_oauth_refresh_token(refresh_token_value)
    if old_refresh is None:
        return Response({"error": "invalid_grant", "error_description": "Invalid or revoked refresh token"}, status=400)

    oauth_app = old_refresh.application
    user = old_refresh.user
    scoped_teams = old_refresh.scoped_teams
    old_scope = old_refresh.access_token.scope if old_refresh.access_token else StripeIntegration.SCOPES

    old_access = old_refresh.access_token
    old_refresh.access_token = None
    old_refresh.revoked = timezone.now()
    old_refresh.save(update_fields=["access_token", "revoked"])

    if old_access:
        old_access.delete()

    new_access_value = generate_random_oauth_access_token(None)
    new_access = OAuthAccessToken.objects.create(
        application=oauth_app,
        token=new_access_value,
        user=user,
        expires=timezone.now() + timedelta(seconds=ACCESS_TOKEN_EXPIRY_SECONDS),
        scope=old_scope,
        scoped_teams=scoped_teams,
    )

    new_refresh_value = generate_random_oauth_refresh_token(None)
    OAuthRefreshToken.objects.create(
        application=oauth_app,
        token=new_refresh_value,
        user=user,
        access_token=new_access,
        scoped_teams=scoped_teams,
    )

    return Response(
        {
            "token_type": "bearer",
            "access_token": new_access_value,
            "refresh_token": new_refresh_value,
            "expires_in": ACCESS_TOKEN_EXPIRY_SECONDS,
        }
    )


# ---------------------------------------------------------------------------
# POST /provisioning/resources
# ---------------------------------------------------------------------------


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def provisioning_resources_create(request: Request) -> Response:
    auth_error, user, access_token = _authenticate_bearer(request)
    if auth_error:
        return auth_error

    error = verify_stripe_signature(request)
    if error:
        return error
    if error := verify_api_version(request):
        return error

    service_id = request.data.get("service_id", "")
    if service_id and service_id not in VALID_SERVICE_IDS:
        return _error_response("unknown_service", f"Unknown service_id: {service_id}")

    scoped_teams = access_token.scoped_teams or []

    if not scoped_teams:
        return _error_response("no_team", "No team associated with this token")

    team_id = scoped_teams[0]
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return _error_response("team_not_found", "Team not found", resource_id=str(team_id), status=404)

    resolved_service_id = service_id or POSTHOG_SERVICE_ID
    cache.set(f"{RESOURCE_SERVICE_CACHE_PREFIX}{team_id}", resolved_service_id, timeout=None)

    region = get_instance_region() or "US"
    host = _region_to_host(region)

    return Response(
        {
            "status": "complete",
            "id": str(team_id),
            "service_id": resolved_service_id,
            "complete": {
                "access_configuration": {
                    "api_key": team.api_token,
                    "host": host,
                },
            },
        }
    )


# ---------------------------------------------------------------------------
# GET /provisioning/resources/:id
# ---------------------------------------------------------------------------


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def provisioning_resource_detail(request: Request, resource_id: str) -> Response:
    return _resolve_resource_response(request, resource_id)


# ---------------------------------------------------------------------------
# POST /provisioning/resources/:id/rotate_credentials
# ---------------------------------------------------------------------------


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def provisioning_rotate_credentials(request: Request, resource_id: str) -> Response:
    auth_error, user, access_token = _authenticate_bearer(request)
    if auth_error:
        return auth_error

    error = verify_stripe_signature(request)
    if error:
        return error
    if error := verify_api_version(request):
        return error

    scoped_teams = access_token.scoped_teams or []

    try:
        team_id = int(resource_id)
    except (ValueError, TypeError):
        return _error_response("invalid_resource_id", "Invalid resource ID", resource_id=resource_id)

    if team_id not in scoped_teams:
        return _error_response(
            "forbidden", "Resource not accessible with this token", resource_id=resource_id, status=403
        )

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return _error_response("not_found", "Resource not found", resource_id=resource_id, status=404)

    try:
        team.reset_token_and_save(user=user, is_impersonated_session=False)
    except Exception:
        capture_exception(additional_properties={"team_id": team_id})
        return _error_response(
            "credential_rotation_failed", "Failed to rotate credentials", resource_id=resource_id, status=500
        )

    service_id = cache.get(f"{RESOURCE_SERVICE_CACHE_PREFIX}{team_id}") or POSTHOG_SERVICE_ID
    region = get_instance_region() or "US"
    host = _region_to_host(region)

    return Response(
        {
            "status": "complete",
            "id": resource_id,
            "service_id": service_id,
            "complete": {
                "access_configuration": {
                    "api_key": team.api_token,
                    "host": host,
                },
            },
        }
    )


def _resolve_resource_response(request: Request, resource_id: str) -> Response:
    auth_error, user, access_token = _authenticate_bearer(request)
    if auth_error:
        return auth_error

    error = verify_stripe_signature(request)
    if error:
        return error
    if error := verify_api_version(request):
        return error

    scoped_teams = access_token.scoped_teams or []

    try:
        team_id = int(resource_id)
    except (ValueError, TypeError):
        return Response(
            {
                "status": "error",
                "id": resource_id,
                "error": {"code": "invalid_resource_id", "message": "Invalid resource ID"},
            },
            status=400,
        )

    if team_id not in scoped_teams:
        return Response(
            {
                "status": "error",
                "id": resource_id,
                "error": {"code": "forbidden", "message": "Resource not accessible with this token"},
            },
            status=403,
        )

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return Response(
            {"status": "error", "id": resource_id, "error": {"code": "not_found", "message": "Resource not found"}},
            status=404,
        )

    service_id = cache.get(f"{RESOURCE_SERVICE_CACHE_PREFIX}{team_id}") or POSTHOG_SERVICE_ID
    region = get_instance_region() or "US"
    host = _region_to_host(region)

    return Response(
        {
            "status": "complete",
            "id": resource_id,
            "service_id": service_id,
            "complete": {
                "access_configuration": {
                    "api_key": team.api_token,
                    "host": host,
                },
            },
        }
    )


# ---------------------------------------------------------------------------
# POST /provisioning/deep_links
# ---------------------------------------------------------------------------


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def deep_links(request: Request) -> Response:
    auth_error, user, access_token = _authenticate_bearer(request)
    if auth_error:
        return auth_error

    error = verify_stripe_signature(request)
    if error:
        return error
    if error := verify_api_version(request):
        return error

    purpose = request.data.get("purpose", "dashboard")
    if purpose not in SUPPORTED_DEEP_LINK_PURPOSES:
        return Response(
            {
                "error": {
                    "code": "unsupported_purpose",
                    "message": f"Unsupported purpose: {purpose}. Supported: {', '.join(sorted(SUPPORTED_DEEP_LINK_PURPOSES))}",
                }
            },
            status=400,
        )

    scoped_teams = access_token.scoped_teams or []
    team_id = scoped_teams[0] if scoped_teams else None

    region = get_instance_region() or "US"
    host = _region_to_host(region)

    token = secrets.token_urlsafe(32)
    cache_key = f"{DEEP_LINK_CACHE_PREFIX}{token}"
    cache.set(
        cache_key,
        {
            "user_id": access_token.user_id,
            "team_id": team_id,
            "purpose": purpose,
        },
        timeout=DEEP_LINK_TTL_SECONDS,
    )

    expires_at = timezone.now() + timedelta(seconds=DEEP_LINK_TTL_SECONDS)

    url = f"{host}/agentic/login?token={token}"
    if team_id:
        url += f"&team_id={team_id}"

    return Response(
        {
            "purpose": purpose,
            "url": url,
            "expires_at": expires_at.isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error_response(code: str, message: str, resource_id: str = "", status: int = 400) -> Response:
    return Response({"status": "error", "id": resource_id, "error": {"code": code, "message": message}}, status=status)


def _authenticate_bearer(request: Request) -> tuple[Response | None, Any, Any]:
    """Authenticate via Bearer token. Returns (error_response, user, access_token)."""
    from .authentication import StripeProvisioningBearerAuthentication

    auth = StripeProvisioningBearerAuthentication()
    try:
        result = auth.authenticate(request)
    except AuthenticationFailed:
        return (_error_response("unauthorized", "Authentication failed", status=401), None, None)
    if result is None:
        return (_error_response("unauthorized", "Missing bearer token", status=401), None, None)
    return None, result[0], result[1]


def _get_stripe_oauth_app():
    from posthog.models.oauth import OAuthApplication

    if settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID:
        try:
            return OAuthApplication.objects.get(client_id=settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID)
        except OAuthApplication.DoesNotExist:
            logger.warning(
                "stripe_app.oauth_app.client_id_not_found",
                client_id=settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID,
            )

    from oauthlib.common import generate_token

    return OAuthApplication.objects.create(
        name=STRIPE_APP_NAME,
        client_id=settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID or generate_token(),
        client_secret="",
        client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
        authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        redirect_uris="https://localhost",
        algorithm="RS256",
    )


def _region_to_host(region: str) -> str:
    region_lower = region.lower()
    if region_lower == "eu":
        return "https://eu.posthog.com"
    elif region_lower in ("us", "dev"):
        return "https://us.posthog.com"
    return settings.SITE_URL


# ---------------------------------------------------------------------------
# GET /agentic/login — deep link login for agentic provisioning users
# ---------------------------------------------------------------------------


def agentic_login(request: Any) -> HttpResponseBase:
    token = request.GET.get("token", "")
    if not token:
        _capture_deep_link_event("missing_token")
        logger.warning("agentic_login.missing_token")
        return HttpResponseRedirect("/?error=missing_token")

    cache_key = f"{DEEP_LINK_CACHE_PREFIX}{token}"

    try:
        link_data = cache.get(cache_key)
    except Exception:
        capture_exception(additional_properties={"cache_key": cache_key})
        return HttpResponseRedirect("/?error=service_unavailable")

    if link_data is None:
        _capture_deep_link_event("expired_or_invalid_token")
        logger.warning("agentic_login.expired_or_invalid_token")
        return HttpResponseRedirect("/?error=expired_or_invalid_token")

    # Atomic delete — if another request already consumed this token, reject
    if not cache.delete(cache_key):
        _capture_deep_link_event("expired_or_invalid_token")
        logger.warning("agentic_login.token_already_consumed")
        return HttpResponseRedirect("/?error=expired_or_invalid_token")

    if not isinstance(link_data, dict):
        _capture_deep_link_event("invalid_token_data")
        logger.warning("agentic_login.invalid_token_data")
        return HttpResponseRedirect("/?error=invalid_token_data")

    user_id = link_data.get("user_id")
    team_id = link_data.get("team_id")
    purpose = link_data.get("purpose", "dashboard")

    if not user_id:
        _capture_deep_link_event("invalid_token_data")
        logger.warning("agentic_login.missing_user_id")
        return HttpResponseRedirect("/?error=invalid_token_data")

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        _capture_deep_link_event("user_not_found", user_id=user_id)
        capture_exception(
            Exception("Deep link login user not found"),
            {"user_id": user_id, "team_id": team_id},
        )
        return HttpResponseRedirect("/?error=user_not_found")

    if not user.is_active:
        _capture_deep_link_event("user_inactive", user_id=user_id)
        logger.warning("agentic_login.user_inactive", user_id=user_id)
        return HttpResponseRedirect("/?error=user_inactive")

    auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    _capture_deep_link_event("success", user_id=user_id, team_id=team_id, purpose=purpose)
    logger.info("agentic_login.success", user_id=user_id, team_id=team_id, purpose=purpose)

    redirect_path = _deep_link_redirect_path(purpose, team_id)
    return HttpResponseRedirect(redirect_path)


def _deep_link_redirect_path(purpose: str, team_id: int | None) -> str:
    if team_id and Team.objects.filter(id=team_id).exists():
        return f"/project/{team_id}"
    return "/"


def _capture_deep_link_event(outcome: str, **extra: object) -> None:
    posthoganalytics.capture(
        "agentic_provisioning deep link login",
        distinct_id="agentic_provisioning_system",
        properties={"outcome": outcome, **extra},
    )
