from __future__ import annotations

import re
import time
import uuid
import secrets
from datetime import timedelta
from typing import Any, cast
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
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import StripeIntegration
from posthog.models.oauth import OAuthAccessToken, OAuthRefreshToken, find_oauth_refresh_token
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import (
    generate_random_oauth_access_token,
    generate_random_oauth_refresh_token,
    generate_random_token_personal,
    mask_key_value,
)
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

_SAFE_STATE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,256}$")

STRIPE_APP_NAME = "PostHog Stripe App"
STRIPE_PROVISIONED_PAT_LABEL_PREFIX = "Stripe Projects"

ACCESS_TOKEN_EXPIRY_SECONDS = 365 * 24 * 3600


# ---------------------------------------------------------------------------
# Service catalog — three services:
#   1. free (plan) — generous free tier, no credit card required
#   2. pay_as_you_go (plan) — usage-based pricing, no minimum commitment
#   3. analytics (deployable) — provisions a PostHog project, pricing varies
#      by parent plan via component pricing
# ---------------------------------------------------------------------------

ANALYTICS_SERVICE_ID = "analytics"
FREE_PLAN_SERVICE_ID = "free"
PAY_AS_YOU_GO_SERVICE_ID = "pay_as_you_go"

ALL_CATEGORIES: list[str] = ["analytics", "feature_flags", "ai"]

SERVICES_CACHE_KEY = "agentic_provisioning:services"
SERVICES_CACHE_TTL = 3600
SERVICES_CACHE_RETRY_TTL = 300
SERVICES_CACHE_EXPIRES_KEY = "agentic_provisioning:services:expires_at"
SERVICES_CACHE_STORE_TTL = 86400

_EXCLUDED_PRODUCT_TYPES = {"platform_and_support", "integrations"}

_FALLBACK_DESCRIPTION = "PostHog — product analytics, session replay, realtime destinations, feature flags & experiments, surveys, data warehouse, error tracking, llm analytics, logs, posthog ai, emails, and more."


_PAY_AS_YOU_GO_PRICING_SUMMARY = (
    "$0/mo base. Usage-based: "
    "1M free events then $0.00005/event, "
    "5K free recordings then $0.005/recording, "
    "1M free feature flag requests then $0.0001/request, "
    "and more. See posthog.com/pricing for full details."
)


def _build_free_plan_service() -> dict[str, Any]:
    return {
        "id": FREE_PLAN_SERVICE_ID,
        "description": "Free - generous free tier across all PostHog products, no credit card required.",
        "categories": ALL_CATEGORIES,
        "pricing": {"type": "free"},
        "kind": "plan",
        "allowed_updates": [PAY_AS_YOU_GO_SERVICE_ID],
    }


def _build_pay_as_you_go_service() -> dict[str, Any]:
    return {
        "id": PAY_AS_YOU_GO_SERVICE_ID,
        "description": "Pay-as-you-go - usage-based pricing across all PostHog products with no minimum commitment.",
        "categories": ALL_CATEGORIES,
        "pricing": {
            "type": "paid",
            "paid": {"type": "freeform", "freeform": _PAY_AS_YOU_GO_PRICING_SUMMARY},
        },
        "kind": "plan",
        "allowed_updates": [FREE_PLAN_SERVICE_ID],
    }


def _build_analytics_service(description: str) -> dict[str, Any]:
    return {
        "id": ANALYTICS_SERVICE_ID,
        "description": description,
        "categories": ALL_CATEGORIES,
        "pricing": {
            "type": "component",
            "component": {
                "options": [
                    {"parent_service_ids": [FREE_PLAN_SERVICE_ID], "type": "free"},
                    {
                        "parent_service_ids": [PAY_AS_YOU_GO_SERVICE_ID],
                        "type": "paid",
                        "paid": {"type": "freeform", "freeform": _PAY_AS_YOU_GO_PRICING_SUMMARY},
                    },
                ]
            },
        },
        "kind": "deployable",
        # Stripe validates allowed_updates client-side before calling update_service.
        # Without this, `stripe projects update` rejects plan changes.
        "allowed_updates": ["service_ref"],
    }


def _fetch_services_from_billing() -> list[dict[str, Any]] | None:
    """Fetch product catalog from billing and build the service list."""
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

    product_names = [
        p.get("name", "")
        for p in products
        if p.get("type", "") not in _EXCLUDED_PRODUCT_TYPES and not p.get("inclusion_only")
    ]
    description = f"PostHog — {', '.join(n for n in product_names if n).lower()}, and more."

    return [_build_free_plan_service(), _build_pay_as_you_go_service(), _build_analytics_service(description)]


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

    if cached is not None:
        logger.warning("agentic_provisioning.services.serving_stale_cache")
        cache.set(SERVICES_CACHE_EXPIRES_KEY, now + SERVICES_CACHE_RETRY_TTL, SERVICES_CACHE_STORE_TTL)
        return cached

    logger.warning("agentic_provisioning.services.no_cache_fallback")
    fallback = [
        _build_free_plan_service(),
        _build_pay_as_you_go_service(),
        _build_analytics_service(_FALLBACK_DESCRIPTION),
    ]
    cache.set(SERVICES_CACHE_KEY, fallback, SERVICES_CACHE_RETRY_TTL)
    cache.set(SERVICES_CACHE_EXPIRES_KEY, now + SERVICES_CACHE_RETRY_TTL, SERVICES_CACHE_RETRY_TTL)
    return fallback


VALID_SERVICE_IDS: set[str] = {FREE_PLAN_SERVICE_ID, PAY_AS_YOU_GO_SERVICE_ID, ANALYTICS_SERVICE_ID}


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

    return Response({"data": _get_services()})


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
        _capture_provisioning_event("account_request", "error", error_code="missing_email")
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
            _capture_provisioning_event("account_request", "error", error_code="expired")
            return Response(
                {"type": "error", "error": {"code": "expired", "message": "Account request has expired"}},
                status=400,
            )

    stripe_info = orchestrator.get("stripe") or {}
    stripe_account_id = stripe_info.get("account", "") if orchestrator.get("type") == "stripe" else ""
    if not stripe_account_id:
        _capture_provisioning_event("account_request", "error", error_code="missing_stripe_account")
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

    _capture_provisioning_event("account_request", "existing_user", region=region)

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
            _capture_provisioning_event("account_request", "race_condition_existing_user", region=region)
            return _handle_existing_user(
                request_id, existing, data.get("confirmation_secret", ""), scopes, stripe_account_id, region
            )
        _capture_provisioning_event("account_request", "creation_failed", region=region)
        return Response(
            {
                "id": request_id,
                "type": "error",
                "error": {"code": "account_creation_failed", "message": "Failed to create account"},
            },
            status=500,
        )

    _capture_provisioning_event("account_request", "new_user", region=region)

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
    if not state or not _SAFE_STATE_RE.match(state):
        _capture_provisioning_event("authorize", "missing_state")
        return HttpResponseRedirect(f"{settings.SITE_URL}?error=missing_state")

    pending_key = f"{PENDING_AUTH_CACHE_PREFIX}{state}"
    pending = cache.get(pending_key)
    if pending is None:
        _capture_provisioning_event("authorize", "expired_state")
        return HttpResponseRedirect(f"{settings.SITE_URL}?error=expired_or_invalid_state")

    if request.user.email != pending["email"]:
        _capture_provisioning_event("authorize", "email_mismatch")
        return HttpResponseRedirect(f"{settings.SITE_URL}?error=email_mismatch")

    scope = " ".join(pending.get("scopes", []))

    user = request.user
    memberships = list(user.organization_memberships.select_related("organization").all())
    if not memberships:
        _capture_provisioning_event("authorize", "no_organization")
        return HttpResponseRedirect(f"{settings.SITE_URL}?error=no_organization")

    org_ids = [m.organization_id for m in memberships]
    non_demo_teams = list(Team.objects.filter(organization_id__in=org_ids, is_demo=False))

    if not non_demo_teams:
        organization = memberships[0].organization
        team = Team.objects.create_with_data(initiating_user=user, organization=organization)
        non_demo_teams = [team]
        _capture_provisioning_event("authorize", "auto_created_project", team_id=team.id)

    if len(memberships) == 1 and len(non_demo_teams) == 1:
        cache.delete(pending_key)

        organization = memberships[0].organization
        team = non_demo_teams[0]

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

        _capture_provisioning_event("authorize", "auto_redirect", team_id=team.id)

        callback_url = settings.STRIPE_ORCHESTRATOR_CALLBACK_URL
        sanitized_state = re.sub(r"[^A-Za-z0-9_\-]", "", state)
        params = urlencode({"code": code, "state": sanitized_state})
        return HttpResponseRedirect(f"{callback_url}?{params}")

    _capture_provisioning_event("authorize", "selection_required")

    base = settings.SITE_URL.rstrip("/")
    sanitized_state = re.sub(r"[^A-Za-z0-9_\-]", "", state)
    params = urlencode({"state": sanitized_state, "scope": scope})
    return HttpResponseRedirect(f"{base}/agentic/authorize?{params}")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agentic_authorize_confirm(request: Request) -> Response:
    state = request.data.get("state", "")
    team_id = request.data.get("team_id")

    if not state or team_id is None or not _SAFE_STATE_RE.match(state):
        _capture_provisioning_event("authorize_confirm", "invalid_request")
        return Response({"error": "state and team_id are required"}, status=400)

    pending_key = f"{PENDING_AUTH_CACHE_PREFIX}{state}"
    pending = cache.get(pending_key)
    if pending is None:
        _capture_provisioning_event("authorize_confirm", "expired_state")
        return Response({"error": "expired_or_invalid_state"}, status=400)

    user = cast(User, request.user)

    if user.email != pending["email"]:
        _capture_provisioning_event("authorize_confirm", "email_mismatch")
        return Response({"error": "email_mismatch"}, status=403)

    try:
        team = Team.objects.get(id=team_id, is_demo=False)
    except Team.DoesNotExist:
        _capture_provisioning_event("authorize_confirm", "team_not_found", team_id=team_id)
        return Response({"error": "team_not_found"}, status=404)

    if not user.organization_memberships.filter(organization_id=team.organization_id).exists():
        _capture_provisioning_event("authorize_confirm", "team_not_accessible", team_id=team_id)
        return Response({"error": "team_not_accessible"}, status=403)

    cache.delete(pending_key)

    code = secrets.token_urlsafe(32)
    cache.set(
        f"{AUTH_CODE_CACHE_PREFIX}{code}",
        {
            "user_id": user.id,
            "org_id": str(team.organization_id),
            "team_id": team.id,
            "stripe_account_id": pending.get("stripe_account_id", ""),
            "scopes": pending.get("scopes", []),
            "region": pending.get("region", "US"),
        },
        timeout=AUTH_CODE_TTL_SECONDS,
    )

    callback_url = settings.STRIPE_ORCHESTRATOR_CALLBACK_URL
    sanitized_state = re.sub(r"[^A-Za-z0-9_\-]", "", state)
    params = urlencode({"code": code, "state": sanitized_state})
    redirect_url = f"{callback_url}?{params}"

    _capture_provisioning_event("authorize_confirm", "success", team_id=team_id)

    return Response({"redirect_url": redirect_url})


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
        _capture_provisioning_event("token_exchange", "unsupported_grant_type", grant_type=grant_type)
        return Response(
            {"error": "unsupported_grant_type", "error_description": f"Unsupported grant_type: {grant_type}"},
            status=400,
        )


def _exchange_authorization_code(request: Request) -> Response:
    code = request.data.get("code", "")
    if not code:
        _capture_provisioning_event("token_exchange", "missing_code", grant_type="authorization_code")
        return Response({"error": "invalid_request", "error_description": "code is required"}, status=400)

    cache_key = f"{AUTH_CODE_CACHE_PREFIX}{code}"
    code_data = cache.get(cache_key)
    if code_data is None:
        _capture_provisioning_event("token_exchange", "invalid_code", grant_type="authorization_code")
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
        _capture_provisioning_event("token_exchange", "user_not_found", grant_type="authorization_code")
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

    _capture_provisioning_event("token_exchange", "success", grant_type="authorization_code")

    return Response(
        {
            "token_type": "bearer",
            "access_token": access_token_value,
            "refresh_token": refresh_token_value,
            "expires_in": ACCESS_TOKEN_EXPIRY_SECONDS,
            "account": {
                "id": account_id,
                "payment_credentials": "orchestrator",
            },
        }
    )


def _exchange_refresh_token(request: Request) -> Response:
    refresh_token_value = request.data.get("refresh_token", "")
    if not refresh_token_value:
        _capture_provisioning_event("token_exchange", "missing_refresh_token", grant_type="refresh_token")
        return Response({"error": "invalid_request", "error_description": "refresh_token is required"}, status=400)

    old_refresh = find_oauth_refresh_token(refresh_token_value)
    if old_refresh is None:
        _capture_provisioning_event("token_exchange", "invalid_refresh_token", grant_type="refresh_token")
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

    _capture_provisioning_event("token_exchange", "success", grant_type="refresh_token")

    return Response(
        {
            "token_type": "bearer",
            "access_token": new_access_value,
            "refresh_token": new_refresh_value,
            "expires_in": ACCESS_TOKEN_EXPIRY_SECONDS,
        }
    )


def _activate_billing_with_spt(team: Team, user: User, spt_token: str) -> bool:
    """Call the billing service to activate a subscription with a Stripe Shared Payment Token.

    Returns True if activation succeeded, False otherwise.
    """
    try:
        from posthog.cloud_utils import get_cached_instance_license

        from ee.billing.billing_manager import build_billing_token

        license = get_cached_instance_license()
        if not license:
            capture_exception(Exception("No license found for SPT billing activation"))
            return False

        organization = team.organization
        billing_token = build_billing_token(license, organization, user)

        res = requests.post(
            f"{BILLING_SERVICE_URL}/api/activate/authorize",
            headers={"Authorization": f"Bearer {billing_token}"},
            json={"shared_payment_token": spt_token},
            timeout=30,
        )

        if res.status_code not in (200, 201):
            capture_exception(
                Exception(f"Billing SPT activation failed: {res.status_code}"),
                {"team_id": team.id, "org_id": str(organization.id), "status": res.status_code},
            )
            return False

        logger.info("stripe_app.spt_billing_activated", team_id=team.id, org_id=str(organization.id))
        return True
    except Exception:
        capture_exception(additional_properties={"team_id": team.id, "org_id": str(team.organization_id)})
        return False


def _try_activate_billing_with_spt(request: Request, team: Team, user: User) -> bool | None:
    """Try to activate billing with an SPT from payment_credentials.

    Returns True if succeeded, False if failed, None if no SPT was present.
    """
    payment_credentials = request.data.get("payment_credentials")
    if isinstance(payment_credentials, dict) and payment_credentials.get("type") == "stripe_payment_token":
        spt_token = payment_credentials.get("stripe_payment_token")
        if spt_token:
            return _activate_billing_with_spt(team, user, spt_token)
    return None


def _create_provisioned_pat(user: User, team: Team) -> str | None:
    """Create a Personal API Key for a Stripe-provisioned user and return the raw key value."""
    try:
        api_key_value = generate_random_token_personal()
        label = f"{STRIPE_PROVISIONED_PAT_LABEL_PREFIX} - {team.name}"[:40]

        PersonalAPIKey.objects.create(
            user=user,
            label=label,
            secure_value=hash_key_value(api_key_value),
            mask_value=mask_key_value(api_key_value),
            scopes=[],
        )

        return api_key_value
    except Exception:
        capture_exception(additional_properties={"user_id": user.id, "team_id": team.id})
        return None


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
        _capture_provisioning_event("resource_created", "error", error_code="unknown_service")
        return _error_response("unknown_service", f"Unknown service_id: {service_id}")

    scoped_teams = access_token.scoped_teams or []

    if not scoped_teams:
        _capture_provisioning_event("resource_created", "error", error_code="no_team")
        return _error_response("no_team", "No team associated with this token")

    team_id = scoped_teams[0]
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        _capture_provisioning_event("resource_created", "error", error_code="team_not_found", team_id=team_id)
        return _error_response("team_not_found", "Team not found", resource_id=str(team_id), status=404)

    resolved_service_id = service_id or ANALYTICS_SERVICE_ID
    cache.set(f"{RESOURCE_SERVICE_CACHE_PREFIX}{team_id}", resolved_service_id, timeout=None)

    billing_result = _try_activate_billing_with_spt(request, team, user)
    if billing_result is False:
        return Response(
            {
                "status": "error",
                "id": str(team_id),
                "error": {
                    "code": "requires_payment_credentials",
                    "message": "Billing activation failed",
                },
            },
            status=400,
        )

    region = get_instance_region() or "US"
    host = _region_to_host(region)

    _capture_provisioning_event("resource_created", "success", service_id=resolved_service_id, team_id=team_id)

    access_configuration: dict[str, str] = {
        "api_key": team.api_token,
        "host": host,
    }
    if personal_api_key := _create_provisioned_pat(user, team):
        access_configuration["personal_api_key"] = personal_api_key

    return Response(
        {
            "status": "complete",
            "id": str(team_id),
            "service_id": resolved_service_id,
            "complete": {
                "access_configuration": access_configuration,
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
        _capture_provisioning_event("credential_rotation", "failed", team_id=team_id)
        return _error_response(
            "credential_rotation_failed", "Failed to rotate credentials", resource_id=resource_id, status=500
        )

    _capture_provisioning_event("credential_rotation", "success", team_id=team_id)

    service_id = cache.get(f"{RESOURCE_SERVICE_CACHE_PREFIX}{team_id}") or ANALYTICS_SERVICE_ID
    region = get_instance_region() or "US"
    host = _region_to_host(region)

    access_configuration: dict[str, str] = {
        "api_key": team.api_token,
        "host": host,
    }
    if personal_api_key := _create_provisioned_pat(user, team):
        access_configuration["personal_api_key"] = personal_api_key

    return Response(
        {
            "status": "complete",
            "id": resource_id,
            "service_id": service_id,
            "complete": {
                "access_configuration": access_configuration,
            },
        }
    )


# ---------------------------------------------------------------------------
# POST /provisioning/resources/:id/update_service
# ---------------------------------------------------------------------------


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def provisioning_update_service(request: Request, resource_id: str) -> Response:
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

    service_id = request.data.get("service_id", "")
    if not service_id:
        return _error_response("missing_service_id", "service_id is required", resource_id=resource_id)
    if service_id not in VALID_SERVICE_IDS:
        return _error_response("unknown_service", f"Unknown service_id: {service_id}", resource_id=resource_id)

    billing_result = _try_activate_billing_with_spt(request, team, user)
    if billing_result is False:
        return _error_response(
            "billing_activation_failed",
            "Failed to activate billing with payment credentials",
            resource_id=resource_id,
        )

    cache.set(f"{RESOURCE_SERVICE_CACHE_PREFIX}{team_id}", service_id, timeout=None)

    region = get_instance_region() or "US"
    host = _region_to_host(region)

    _capture_provisioning_event("update_service", "success", service_id=service_id, team_id=team_id)

    access_configuration: dict[str, str] = {
        "api_key": team.api_token,
        "host": host,
    }

    return Response(
        {
            "status": "complete",
            "id": resource_id,
            "service_id": service_id,
            "complete": {
                "access_configuration": access_configuration,
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

    service_id = cache.get(f"{RESOURCE_SERVICE_CACHE_PREFIX}{team_id}") or ANALYTICS_SERVICE_ID
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
        _capture_provisioning_event("deep_link_created", "unsupported_purpose", purpose=purpose)
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

    _capture_provisioning_event("deep_link_created", "success", purpose=purpose, team_id=team_id)

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
    logger.warning("stripe_app.error_response", code=code, message=message, resource_id=resource_id, status=status)
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


def _capture_provisioning_event(event_type: str, outcome: str, **extra: object) -> None:
    team_id = extra.get("team_id")
    distinct_id = f"agentic_provisioning_team_{team_id}" if team_id else f"agentic_provisioning_{uuid.uuid4().hex[:16]}"
    posthoganalytics.capture(
        f"agentic_provisioning {event_type}",
        distinct_id=distinct_id,
        properties={"outcome": outcome, **extra},
    )


def _capture_deep_link_event(outcome: str, **extra: object) -> None:
    _capture_provisioning_event("deep link login", outcome, **extra)
