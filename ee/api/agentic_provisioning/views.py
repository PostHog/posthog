from __future__ import annotations

import re
import time
import uuid
import base64
import hashlib
import secrets
from datetime import timedelta
from typing import Any, cast
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
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

from posthog.api.authentication import password_reset_token_generator
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import StripeIntegration
from posthog.models.oauth import (
    OAuthAccessToken,
    OAuthApplication,
    OAuthRefreshToken,
    find_oauth_access_token,
    find_oauth_refresh_token,
)
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import (
    generate_random_oauth_access_token,
    generate_random_oauth_refresh_token,
    generate_random_token_personal,
    mask_key_value,
)
from posthog.rbac.user_access_control import UserAccessControl
from posthog.tasks.email import send_provisioning_welcome
from posthog.utils import get_instance_region

from ee.settings import BILLING_SERVICE_URL

from . import AUTH_CODE_CACHE_PREFIX, PENDING_AUTH_CACHE_PREFIX
from .authentication import ProvisioningAuthentication
from .region_proxy import region_proxy
from .signature import SUPPORTED_VERSIONS, verify_api_version, verify_provisioning_signature

logger = structlog.get_logger(__name__)

AUTH_CODE_TTL_SECONDS = 300
PENDING_AUTH_TTL_SECONDS = 600
DEEP_LINK_TTL_SECONDS = 600
DEEP_LINK_CACHE_PREFIX = "provisioning_deep_link:"
SUPPORTED_DEEP_LINK_PURPOSES = {"dashboard"}
DEEP_LINK_RATE_LIMIT_PREFIX = "agentic_login_rate:"
DEEP_LINK_RATE_LIMIT_MAX_ATTEMPTS = 10
DEEP_LINK_RATE_LIMIT_WINDOW_SECONDS = 300

CIMD_DOMAIN_RATE_LIMIT_PREFIX = "cimd_registration_domain_rate:"
CIMD_DOMAIN_RATE_LIMIT_MAX = 5
CIMD_DOMAIN_RATE_LIMIT_WINDOW_SECONDS = 3600

PARTNER_RATE_LIMIT_PREFIX = "provisioning_partner_rate:"
PARTNER_RATE_LIMIT_WINDOW_SECONDS = 3600
PARTNER_RATE_LIMIT_DEFAULTS: dict[str, int] = {
    "account_requests": 10,
    "token_exchanges": 20,
    "resource_creates": 20,
}
PARTNER_RATE_LIMIT_EVENT_NAMES: dict[str, str] = {
    "account_requests": "account_request",
    "token_exchanges": "token_exchange",
    "resource_creates": "resource_created",
}

_SAFE_STATE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,256}$")

LEGACY_STRIPE_APP_NAME = "PostHog Stripe App"
PROVISIONED_PAT_LABEL_PREFIX = "Stripe Projects"

ACCESS_TOKEN_EXPIRY_SECONDS = 365 * 24 * 3600
PARTNER_TOKEN_EXPIRY_SECONDS = 3600


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
            "paid": {
                "type": "freeform",
                "freeform": "$0/mo base, usage-based pricing. See https://posthog.com/pricing for rates.",
            },
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
                        "paid": {"type": "freeform", "freeform": "Usage-based pricing, pay only for what you use."},
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
    error = verify_provisioning_signature(request)
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
    error = verify_provisioning_signature(request)
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
@region_proxy(strategy="body_region")
def account_requests(request: Request) -> Response:
    if error := verify_api_version(request):
        return error

    if error := _enforce_cimd_registration_throttle(request):
        return error

    # --- Identify partner ---
    auth = ProvisioningAuthentication()
    partner = None
    try:
        result = auth.authenticate(request)
        if result:
            _, partner = result
    except AuthenticationFailed:
        return Response(
            {"type": "error", "error": {"code": "unauthorized", "message": "Authentication failed"}},
            status=401,
        )

    if partner is None and auth.cimd_registration_pending:
        return Response(
            {"type": "registering", "retry_after": 5},
            status=202,
        )

    # --- Parse request ---
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

    # Partner account ID: generic field, with Stripe backward compat
    orchestrator_type = orchestrator.get("type", "")
    if orchestrator_type == "stripe":
        stripe_info = orchestrator.get("stripe") or {}
        partner_account_id = stripe_info.get("account", "")
    else:
        partner_account_id = orchestrator.get("account", "")

    # If no partner identified, require Stripe Projects HMAC auth
    if not partner and not request.headers.get("stripe-signature"):
        return Response(
            {"type": "error", "error": {"code": "unauthorized", "message": "Authentication required"}},
            status=401,
        )

    if not partner:
        if error := _verify_hmac_if_present(request):
            return error

    # Stripe Projects: require stripe account if no provisioning partner identified
    if not partner and not partner_account_id:
        _capture_provisioning_event("account_request", "error", error_code="missing_stripe_account")
        return Response(
            {
                "type": "error",
                "error": {"code": "invalid_request", "message": "orchestrator.stripe.account is required"},
            },
            status=400,
        )

    # Check permission
    if partner and not partner.provisioning_can_create_accounts:
        _capture_provisioning_event("account_request", "error", error_code="account_creation_disabled")
        return Response(
            {
                "type": "error",
                "error": {"code": "forbidden", "message": "Account creation is not enabled for this partner"},
            },
            status=403,
        )

    if partner and (error := _enforce_partner_rate_limit(partner, "account_requests")):
        return error

    # PKCE: capture code_challenge for later verification
    code_challenge = data.get("code_challenge", "")
    code_challenge_method = data.get("code_challenge_method", "S256")
    if code_challenge and code_challenge_method != "S256":
        return Response(
            {
                "type": "error",
                "error": {"code": "invalid_request", "message": "Only S256 code_challenge_method is supported"},
            },
            status=400,
        )
    if code_challenge and (
        len(code_challenge) < 43 or len(code_challenge) > 128 or not re.fullmatch(r"[A-Za-z0-9_\-]+", code_challenge)
    ):
        return Response(
            {
                "type": "error",
                "error": {
                    "code": "invalid_request",
                    "message": "code_challenge must be 43-128 characters using base64url charset",
                },
            },
            status=400,
        )

    region = (configuration.get("region") or "US").upper()

    requested_team_id = configuration.get("team_id")
    if requested_team_id is not None:
        try:
            requested_team_id = int(requested_team_id)
        except (ValueError, TypeError):
            return Response(
                {
                    "id": request_id,
                    "type": "error",
                    "error": {"code": "invalid_request", "message": "configuration.team_id must be an integer"},
                },
                status=400,
            )

    existing_user = User.objects.filter(email=email).first()

    if existing_user:
        return _handle_existing_user(
            request_id,
            existing_user,
            confirmation_secret,
            scopes,
            partner_account_id,
            region,
            requested_team_id,
            partner,
            code_challenge,
            code_challenge_method,
        )

    return _handle_new_user(
        request_id, data, email, scopes, partner_account_id, region, partner, code_challenge, code_challenge_method
    )


def _handle_existing_user(
    request_id: str,
    user: User,
    confirmation_secret: str,
    scopes: list[str],
    partner_account_id: str = "",
    region: str = "US",
    team_id: int | None = None,
    partner: OAuthApplication | None = None,
    code_challenge: str = "",
    code_challenge_method: str = "S256",
) -> Response:
    if partner and not partner.provisioning_skip_existing_user_consent:
        if not code_challenge:
            return Response(
                {
                    "id": request_id,
                    "type": "error",
                    "error": {"code": "invalid_request", "message": "code_challenge is required for public clients"},
                },
                status=400,
            )
        validated_scopes = _validate_scopes(scopes)
        if validated_scopes is None:
            return Response(
                {
                    "id": request_id,
                    "type": "error",
                    "error": {"code": "invalid_scope", "message": "One or more requested scopes are not recognized"},
                },
                status=400,
            )
        return _require_user_consent(
            request_id,
            user,
            validated_scopes,
            partner_account_id,
            region,
            partner,
            code_challenge,
            code_challenge_method,
        )

    team = _resolve_team_for_existing_user(user, team_id)
    if team is None:
        _capture_provisioning_event("account_request", "error", error_code="team_resolution_failed")
        return Response(
            {
                "id": request_id,
                "type": "error",
                "error": {"code": "team_resolution_failed", "message": "Could not resolve a project for this user"},
            },
            status=400,
        )

    code = secrets.token_urlsafe(32)
    cache.set(
        f"{AUTH_CODE_CACHE_PREFIX}{code}",
        {
            "user_id": user.id,
            "org_id": str(team.organization_id),
            "team_id": team.id,
            "stripe_account_id": partner_account_id,
            "partner_id": str(partner.id) if partner else "",
            "scopes": scopes,
            "region": region,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        },
        timeout=AUTH_CODE_TTL_SECONDS,
    )

    _capture_provisioning_event("account_request", "existing_user", region=region, team_id=team.id)

    return Response({"id": request_id, "type": "oauth", "oauth": {"code": code}})


def _require_user_consent(
    request_id: str,
    user: User,
    scopes: list[str],
    partner_account_id: str,
    region: str,
    partner: OAuthApplication,
    code_challenge: str,
    code_challenge_method: str,
) -> Response:
    # Dedup: overwrite any prior pending state for same partner+email so
    # retries don't leave multiple live consent URLs.
    dedup_key = f"pending_auth_state:{partner.id}:{user.email}"
    old_state = cache.get(dedup_key)
    if old_state:
        cache.delete(f"{PENDING_AUTH_CACHE_PREFIX}{old_state}")

    state = secrets.token_urlsafe(32)
    cache.set(dedup_key, state, timeout=PENDING_AUTH_TTL_SECONDS)

    pending_key = f"{PENDING_AUTH_CACHE_PREFIX}{state}"
    cache.set(
        pending_key,
        {
            "email": user.email,
            "scopes": scopes,
            "stripe_account_id": partner_account_id,
            "partner_id": str(partner.id),
            "partner_name": partner.name,
            "region": region,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        },
        timeout=PENDING_AUTH_TTL_SECONDS,
    )

    auth_url = _build_authorize_url(state, scopes, region=region)

    _capture_provisioning_event("account_request", "requires_auth", region=region)

    return Response(
        {
            "id": request_id,
            "type": "requires_auth",
            "requires_auth": {"url": auth_url},
        }
    )


def _resolve_team_for_existing_user(user: User, requested_team_id: int | None = None) -> Team | None:
    """Pick a team for an existing user during email-based account linking.

    If requested_team_id is provided and the user has access, use it.
    Otherwise auto-select: single non-demo team → use it, only demo teams →
    create a new project, multiple teams → create a new project in the first org.
    """
    memberships = list(user.organization_memberships.select_related("organization").all())
    if not memberships:
        return None

    org_ids = [m.organization_id for m in memberships]

    if requested_team_id is not None:
        try:
            team = Team.objects.get(id=requested_team_id, is_demo=False)
        except Team.DoesNotExist:
            return None
        if team.organization_id not in org_ids:
            return None
        return team

    non_demo_teams = list(Team.objects.filter(organization_id__in=org_ids, is_demo=False))

    if len(non_demo_teams) == 1:
        return non_demo_teams[0]

    organization = memberships[0].organization
    return Team.objects.create_with_data(initiating_user=user, organization=organization)


def _handle_new_user(
    request_id: str,
    data: dict,
    email: str,
    scopes: list[str],
    partner_account_id: str,
    region: str,
    partner: OAuthApplication | None = None,
    code_challenge: str = "",
    code_challenge_method: str = "S256",
) -> Response:
    name = data.get("name", "")
    first_name = name.split(" ")[0] if name else ""

    configuration = data.get("configuration")
    if not isinstance(configuration, dict):
        configuration = {}

    partner_label = _partner_label(partner)
    org_name = configuration.get("organization_name") or f"{partner_label} ({email})"

    try:
        organization, team, user = User.objects.bootstrap(
            organization_name=org_name,
            email=email,
            password=None,
            first_name=first_name,
        )
    except IntegrityError:
        existing = User.objects.filter(email=email).first()
        if existing:
            _capture_provisioning_event("account_request", "race_condition_existing_user", region=region)
            return _handle_existing_user(
                request_id,
                existing,
                data.get("confirmation_secret", ""),
                scopes,
                partner_account_id,
                region,
                None,
                partner,
                code_challenge,
                code_challenge_method,
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

    try:
        reset_token = password_reset_token_generator.make_token(user)
        send_provisioning_welcome.delay(user.id, reset_token, partner_label)
    except Exception:
        capture_exception(additional_properties={"user_id": user.id, "step": "provisioning_welcome_email"})

    code = secrets.token_urlsafe(32)
    cache_key = f"{AUTH_CODE_CACHE_PREFIX}{code}"
    cache.set(
        cache_key,
        {
            "user_id": user.id,
            "org_id": str(organization.id),
            "team_id": team.id,
            "stripe_account_id": partner_account_id,
            "partner_id": str(partner.id) if partner else "",
            "scopes": scopes,
            "region": region,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        },
        timeout=AUTH_CODE_TTL_SECONDS,
    )

    return Response({"id": request_id, "type": "oauth", "oauth": {"code": code}})


def _build_authorize_url(confirmation_secret: str, scopes: list[str], region: str = "") -> str:
    base = _region_to_host(region).rstrip("/") if region else settings.SITE_URL.rstrip("/")
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

    # Re-check partner is still active (could have been deactivated since account_requests)
    partner_id = pending.get("partner_id", "")
    is_trusted_partner = not partner_id
    if partner_id:
        try:
            partner_app = OAuthApplication.objects.get(id=partner_id)
            if not partner_app.provisioning_active:
                cache.delete(pending_key)
                _capture_provisioning_event("authorize", "partner_deactivated")
                return HttpResponseRedirect(f"{settings.SITE_URL}?error=partner_deactivated")
            is_trusted_partner = partner_app.provisioning_skip_existing_user_consent
        except OAuthApplication.DoesNotExist:
            pass

    if is_trusted_partner and len(memberships) == 1 and len(non_demo_teams) == 1:
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
                "partner_id": pending.get("partner_id", ""),
                "scopes": pending.get("scopes", []),
                "region": pending.get("region", "US"),
                "code_challenge": pending.get("code_challenge", ""),
                "code_challenge_method": pending.get("code_challenge_method", "S256"),
            },
            timeout=AUTH_CODE_TTL_SECONDS,
        )
        cache.delete(pending_key)

        _capture_provisioning_event("authorize", "auto_redirect", team_id=team.id)

        callback_url = _get_callback_url(pending.get("partner_id", ""))
        sanitized_state = re.sub(r"[^A-Za-z0-9_\-]", "", state)
        params = urlencode({"code": code, "state": sanitized_state})
        return HttpResponseRedirect(f"{callback_url}?{params}")

    _capture_provisioning_event("authorize", "selection_required")

    base = settings.SITE_URL.rstrip("/")
    sanitized_state = re.sub(r"[^A-Za-z0-9_\-]", "", state)
    params = urlencode({"state": sanitized_state})
    return HttpResponseRedirect(f"{base}/agentic/authorize?{params}")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agentic_authorize_pending(request: Request) -> Response:
    """Return server-verified partner name and scopes for a pending auth state.

    The frontend calls this instead of reading from URL params, preventing
    an attacker from spoofing the partner identity on the consent page.
    """
    state = request.query_params.get("state", "")
    if not state or not _SAFE_STATE_RE.match(state):
        return Response({"error": "invalid_state"}, status=400)

    pending = cache.get(f"{PENDING_AUTH_CACHE_PREFIX}{state}")
    if pending is None:
        return Response({"error": "expired_or_invalid_state"}, status=400)

    user = cast(User, request.user)
    if user.email != pending["email"]:
        return Response({"error": "email_mismatch"}, status=403)

    return Response(
        {
            "partner_name": pending.get("partner_name", "the requesting app"),
            "scopes": pending.get("scopes", []),
        }
    )


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

    confirm_partner_id = pending.get("partner_id", "")
    if confirm_partner_id:
        try:
            confirm_partner = OAuthApplication.objects.get(id=confirm_partner_id)
            if not confirm_partner.provisioning_active:
                cache.delete(pending_key)
                _capture_provisioning_event("authorize_confirm", "partner_deactivated")
                return Response({"error": "partner_deactivated"}, status=403)
        except OAuthApplication.DoesNotExist:
            pass

    code = secrets.token_urlsafe(32)
    # Set auth code BEFORE deleting pending state so a cache hiccup
    # between the two doesn't leave the user with no recovery path.
    cache.set(
        f"{AUTH_CODE_CACHE_PREFIX}{code}",
        {
            "user_id": user.id,
            "org_id": str(team.organization_id),
            "team_id": team.id,
            "stripe_account_id": pending.get("stripe_account_id", ""),
            "partner_id": pending.get("partner_id", ""),
            "scopes": pending.get("scopes", []),
            "region": pending.get("region", "US"),
            "code_challenge": pending.get("code_challenge", ""),
            "code_challenge_method": pending.get("code_challenge_method", "S256"),
        },
        timeout=AUTH_CODE_TTL_SECONDS,
    )
    cache.delete(pending_key)

    callback_url = _get_callback_url(pending.get("partner_id", ""))
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
@region_proxy(strategy="token_lookup")
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

    # Auth check: PKCE codes require code_verifier, non-PKCE codes require HMAC.
    # All verification happens BEFORE cache.delete so a failed attempt doesn't consume the code.
    stored_challenge = code_data.get("code_challenge", "")
    has_hmac = bool(request.headers.get("stripe-signature"))
    if stored_challenge:
        code_verifier = request.data.get("code_verifier", "")
        if not code_verifier:
            _capture_provisioning_event("token_exchange", "missing_code_verifier", grant_type="authorization_code")
            return Response(
                {"error": "invalid_request", "error_description": "code_verifier is required for PKCE"}, status=401
            )
        computed = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        if computed != stored_challenge:
            _capture_provisioning_event("token_exchange", "pkce_mismatch", grant_type="authorization_code")
            return Response(
                {"error": "invalid_grant", "error_description": "PKCE code_verifier does not match"}, status=400
            )
    elif not has_hmac:
        _capture_provisioning_event("token_exchange", "missing_signature", grant_type="authorization_code")
        return Response({"error": "invalid_request", "error_description": "Authentication required"}, status=401)
    else:
        if error := _verify_hmac_if_present(request):
            return error

    # Consume the code before rate limiting so a leaked auth code can't be replayed
    # to burn the partner's bucket. Auth codes are single-use by spec, so the
    # tradeoff (rate-limited client loses the code) is acceptable — clients can
    # re-initiate the OAuth flow if rate-limited.
    cache.delete(cache_key)

    partner_id = code_data.get("partner_id", "")
    if partner_id:
        try:
            partner = OAuthApplication.objects.get(id=partner_id)
            if error := _enforce_partner_rate_limit(partner, "token_exchanges"):
                return error
        except (OAuthApplication.DoesNotExist, ValidationError, ValueError):
            logger.warning("partner_rate_limit_app_missing", partner_id=partner_id)

    user_id = code_data["user_id"]
    team_id = code_data["team_id"]
    scopes = code_data.get("scopes", [])

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        _capture_provisioning_event("token_exchange", "user_not_found", grant_type="authorization_code")
        return Response({"error": "invalid_grant", "error_description": "User not found"}, status=400)

    # Use partner's OAuth app if available, fall back to Stripe
    oauth_app = _get_oauth_app_for_code(code_data)
    scope_str = " ".join(scopes) if scopes else StripeIntegration.SCOPES

    token_expiry = (
        PARTNER_TOKEN_EXPIRY_SECONDS if oauth_app and oauth_app.is_provisioning_partner else ACCESS_TOKEN_EXPIRY_SECONDS
    )

    access_token_value = generate_random_oauth_access_token(None)
    access_token = OAuthAccessToken.objects.create(
        application=oauth_app,
        token=access_token_value,
        user=user,
        expires=timezone.now() + timedelta(seconds=token_expiry),
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

    available_teams = _get_available_teams_for_user(user)

    _capture_provisioning_event("token_exchange", "success", grant_type="authorization_code")

    return Response(
        {
            "token_type": "bearer",
            "access_token": access_token_value,
            "refresh_token": refresh_token_value,
            "expires_in": token_expiry,
            "account": {
                "id": account_id,
                "payment_credentials": "orchestrator",
                "available_teams": available_teams,
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

    # provisioning_partner_type is a stable marker set at partner registration;
    # checking it instead of is_provisioning_partner prevents a bypass when an admin
    # clears provisioning_auth_method to disable a partner without revoking tokens.
    if oauth_app and oauth_app.provisioning_partner_type:
        if error := _enforce_partner_rate_limit(oauth_app, "token_exchanges"):
            return error

    old_access = old_refresh.access_token
    old_refresh.access_token = None
    old_refresh.revoked = timezone.now()
    old_refresh.save(update_fields=["access_token", "revoked"])

    if old_access:
        old_access.delete()

    token_expiry = (
        PARTNER_TOKEN_EXPIRY_SECONDS if oauth_app and oauth_app.is_provisioning_partner else ACCESS_TOKEN_EXPIRY_SECONDS
    )

    new_access_value = generate_random_oauth_access_token(None)
    new_access = OAuthAccessToken.objects.create(
        application=oauth_app,
        token=new_access_value,
        user=user,
        expires=timezone.now() + timedelta(seconds=token_expiry),
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
            "expires_in": token_expiry,
        }
    )


def _build_billing_token(team: Team, user: User) -> str | None:
    from posthog.cloud_utils import get_cached_instance_license

    from ee.billing.billing_manager import build_billing_token

    license = get_cached_instance_license()
    if not license:
        return None
    return build_billing_token(license, team.organization, user)


def _team_has_active_billing(team: Team, user: User) -> bool:
    """Check if the team's organization already has an active billing subscription."""
    try:
        billing_token = _build_billing_token(team, user)
        if not billing_token:
            return False

        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing",
            headers={"Authorization": f"Bearer {billing_token}"},
            timeout=30,
        )

        if res.status_code != 200:
            return False

        customer = res.json().get("customer", {})
        return bool(customer.get("has_active_subscription"))
    except Exception:
        capture_exception(additional_properties={"team_id": team.id, "org_id": str(team.organization_id)})
        return False


def _activate_billing_with_spt(team: Team, user: User, spt_token: str) -> bool:
    """Call the billing service to activate a subscription with a Stripe Shared Payment Token.

    Returns True if activation succeeded, False otherwise.
    """
    try:
        billing_token = _build_billing_token(team, user)
        if not billing_token:
            capture_exception(Exception("No license found for SPT billing activation"))
            return False

        res = requests.post(
            f"{BILLING_SERVICE_URL}/api/activate/authorize",
            headers={"Authorization": f"Bearer {billing_token}"},
            json={"shared_payment_token": spt_token},
            timeout=30,
        )

        if res.status_code not in (200, 201):
            capture_exception(
                Exception(f"Billing SPT activation failed: {res.status_code}"),
                {"team_id": team.id, "org_id": str(team.organization_id), "status": res.status_code},
            )
            return False

        logger.info("provisioning.spt_billing_activated", team_id=team.id, org_id=str(team.organization_id))
        return True
    except Exception:
        capture_exception(additional_properties={"team_id": team.id, "org_id": str(team.organization_id)})
        return False


def _extract_spt(request: Request) -> str | None:
    payment_credentials = request.data.get("payment_credentials")
    if isinstance(payment_credentials, dict) and payment_credentials.get("type") == "stripe_payment_token":
        return payment_credentials.get("stripe_payment_token") or None
    return None


def _try_activate_billing_with_spt(request: Request, team: Team, user: User) -> bool | None:
    """Activate billing if an SPT is present, skipping if billing is already active.

    Returns True if succeeded or already active, False if failed, None if no SPT was present.
    """
    spt_token = _extract_spt(request)
    if not spt_token:
        return None
    if _team_has_active_billing(team, user):
        return True
    return _activate_billing_with_spt(team, user, spt_token)


def _create_provisioned_pat(user: User, team: Team) -> str | None:
    """Create a Personal API Key for a provisioned user and return the raw key value."""
    try:
        api_key_value = generate_random_token_personal()
        label = f"{PROVISIONED_PAT_LABEL_PREFIX} - {team.name}"[:40]

        PersonalAPIKey.objects.create(
            user=user,
            label=label,
            secure_value=hash_key_value(api_key_value),
            mask_value=mask_key_value(api_key_value),
            scopes=[],
            scoped_teams=[team.id],
            scoped_organizations=[str(team.organization_id)],
        )

        return api_key_value
    except Exception:
        capture_exception(additional_properties={"user_id": user.id, "team_id": team.id})
        return None


def _resolve_or_create_project_team(
    project_id: str,
    scoped_teams: list[int],
    user: User,
    configuration: dict,
    access_token: OAuthAccessToken,
) -> tuple[Team | None, list[int]]:
    """Look up or create a team for the given project_id.

    Uses TeamProvisioningConfig (DB-backed with unique constraint) for the
    project_id → team_id mapping. This ensures idempotency even across cache
    evictions and handles race conditions via IntegrityError.

    Returns (None, scoped_teams) when an existing team is resolved but the
    authenticated user lacks team-level access (honors advanced permissions
    / access controls on top of org membership).
    """
    from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

    existing = (
        TeamProvisioningConfig.objects.filter(
            stripe_project_id=project_id,
            team__organization_id__in=Team.objects.filter(id__in=scoped_teams).values("organization_id"),
        )
        .select_related("team")
        .first()
    )
    if existing:
        if not _user_can_access_team(user, existing.team):
            return None, scoped_teams
        return _ensure_team_in_token_scopes(access_token, scoped_teams, existing.team)

    base_team = Team.objects.get(id=scoped_teams[0])
    if not _user_can_access_team(user, base_team):
        return None, scoped_teams

    project_name = configuration.get("project_name", "Default project")
    new_team = Team.objects.create_with_data(
        initiating_user=user,
        organization=base_team.organization,
        name=project_name,
    )

    try:
        TeamProvisioningConfig.objects.update_or_create(
            team=new_team,
            defaults={"stripe_project_id": project_id},
        )
    except IntegrityError:
        new_team.delete()
        race_winner = (
            TeamProvisioningConfig.objects.filter(
                stripe_project_id=project_id,
                team__organization_id__in=Team.objects.filter(id__in=scoped_teams).values("organization_id"),
            )
            .select_related("team")
            .first()
        )
        if race_winner:
            if not _user_can_access_team(user, race_winner.team):
                return None, scoped_teams
            return _ensure_team_in_token_scopes(access_token, scoped_teams, race_winner.team)
        raise _ProjectIdCollisionError(project_id)

    return _ensure_team_in_token_scopes(access_token, scoped_teams, new_team)


class _ProjectIdCollisionError(Exception):
    """Raised when a stripe_project_id is already in use by a team outside the caller's orgs."""

    def __init__(self, project_id: str) -> None:
        super().__init__(project_id)
        self.project_id = project_id


def _ensure_team_in_token_scopes(
    access_token: OAuthAccessToken, scoped_teams: list[int], team: Team
) -> tuple[Team, list[int]]:
    if team.id in scoped_teams:
        return team, scoped_teams
    _add_team_to_token_scopes(access_token, team.id)
    return team, [*scoped_teams, team.id]


def _user_can_access_team(user: User, team: Team) -> bool:
    """Verify the user has at least member-level access to the team.

    Org membership alone does not prove access for advanced-permissions
    orgs that restrict individual teams. Without this check the agentic
    provisioning resolve flow could grant scoped access to a private team
    as long as the user had any team in the same org.
    """
    return UserAccessControl(user=user, team=team).check_access_level_for_object(team, required_level="member")


def _add_team_to_token_scopes(access_token: OAuthAccessToken, team_id: int) -> None:
    with transaction.atomic():
        locked_access_token = OAuthAccessToken.objects.select_for_update().get(pk=access_token.pk)
        teams = list(locked_access_token.scoped_teams or [])
        if team_id not in teams:
            teams.append(team_id)
            locked_access_token.scoped_teams = teams
            locked_access_token.save(update_fields=["scoped_teams"])
            access_token.scoped_teams = teams

        refresh_tokens = OAuthRefreshToken.objects.select_for_update().filter(access_token=locked_access_token)
        for rt in refresh_tokens:
            rt_teams = list(rt.scoped_teams or [])
            if team_id not in rt_teams:
                rt_teams.append(team_id)
                rt.scoped_teams = rt_teams
                rt.save(update_fields=["scoped_teams"])


def _get_provisioning_service_id(team: Team) -> str:
    from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

    try:
        config = TeamProvisioningConfig.objects.get(team=team)
        return config.service_id
    except TeamProvisioningConfig.DoesNotExist:
        return ANALYTICS_SERVICE_ID


def _set_provisioning_service_id(team: Team, service_id: str) -> None:
    from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

    TeamProvisioningConfig.objects.update_or_create(
        team=team,
        defaults={"service_id": service_id},
    )


# ---------------------------------------------------------------------------
# POST /provisioning/resources
# ---------------------------------------------------------------------------


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@region_proxy(strategy="bearer_lookup")
def provisioning_resources_create(request: Request) -> Response:
    auth_error, user, access_token = _authenticate_bearer(request)
    if auth_error:
        return auth_error

    if error := _verify_hmac_if_present(request):
        return error
    if error := verify_api_version(request):
        return error

    app = access_token.application
    if app and app.provisioning_partner_type:
        if error := _enforce_partner_rate_limit(app, "resource_creates"):
            # Resource endpoints use {"status": "error"} envelope, not {"type": "error"}
            retry_after = error["Retry-After"] if "Retry-After" in error else "3600"
            response = _error_response(
                "rate_limited", "Rate limit exceeded for this partner. Try again later.", status=429
            )
            response["Retry-After"] = retry_after
            return response

    service_id = request.data.get("service_id", "")
    if service_id and service_id not in VALID_SERVICE_IDS:
        _capture_provisioning_event("resource_created", "error", error_code="unknown_service")
        return _error_response("unknown_service", f"Unknown service_id: {service_id}")

    scoped_teams = access_token.scoped_teams or []

    if not scoped_teams:
        _capture_provisioning_event("resource_created", "error", error_code="no_team")
        return _error_response("no_team", "No team associated with this token")

    project_id = request.data.get("project_id", "")
    configuration = request.data.get("configuration") or {}

    if project_id:
        try:
            team, scoped_teams = _resolve_or_create_project_team(
                project_id, scoped_teams, user, configuration, access_token
            )
        except _ProjectIdCollisionError:
            _capture_provisioning_event(
                "resource_created", "error", error_code="project_id_conflict", project_id=project_id
            )
            return _error_response(
                "project_id_conflict",
                "Project ID already linked to another organization",
                status=409,
            )
        if team is None:
            _capture_provisioning_event("resource_created", "error", error_code="not_found", project_id=project_id)
            return _error_response("not_found", "Resource not found", status=404)
    else:
        team_id = scoped_teams[0]
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            _capture_provisioning_event("resource_created", "error", error_code="team_not_found", team_id=team_id)
            return _error_response("team_not_found", "Team not found", resource_id=str(team_id), status=404)

    resolved_service_id = service_id or ANALYTICS_SERVICE_ID
    _set_provisioning_service_id(team, resolved_service_id)

    billing_result = _try_activate_billing_with_spt(request, team, user)
    has_spt = billing_result is not None
    if billing_result is False:
        _capture_provisioning_event(
            "resource_created",
            "error",
            error_code="requires_payment_credentials",
            service_id=resolved_service_id,
            team_id=team.id,
            has_spt=has_spt,
        )
        return Response(
            {
                "status": "error",
                "id": str(team.id),
                "error": {
                    "code": "requires_payment_credentials",
                    "message": "Billing activation failed",
                },
            },
            status=400,
        )

    if resolved_service_id == PAY_AS_YOU_GO_SERVICE_ID and billing_result is None:
        _capture_provisioning_event(
            "resource_created",
            "error",
            error_code="requires_payment_credentials",
            service_id=resolved_service_id,
            team_id=team.id,
        )
        return _error_response("requires_payment_credentials", "Payment credentials required for paid plan")

    region = get_instance_region() or "US"
    host = _region_to_host(region)

    _capture_provisioning_event(
        "resource_created",
        "success",
        service_id=resolved_service_id,
        team_id=team.id,
        has_spt=has_spt,
        billing_result=str(billing_result),
    )

    access_configuration: dict[str, str] = {
        "api_key": team.api_token,
        "host": host,
    }
    if personal_api_key := _create_provisioned_pat(user, team):
        access_configuration["personal_api_key"] = personal_api_key

    return Response(
        {
            "status": "complete",
            "id": str(team.id),
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
@region_proxy(strategy="bearer_lookup")
def provisioning_resource_detail(request: Request, resource_id: str) -> Response:
    return _resolve_resource_response(request, resource_id)


# ---------------------------------------------------------------------------
# POST /provisioning/resources/:id/rotate_credentials
# ---------------------------------------------------------------------------


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@region_proxy(strategy="bearer_lookup")
def provisioning_rotate_credentials(request: Request, resource_id: str) -> Response:
    auth_error, user, access_token = _authenticate_bearer(request)
    if auth_error:
        return auth_error

    if error := _verify_hmac_if_present(request):
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

    service_id = _get_provisioning_service_id(team)
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
@region_proxy(strategy="bearer_lookup")
def provisioning_update_service(request: Request, resource_id: str) -> Response:
    auth_error, user, access_token = _authenticate_bearer(request)
    if auth_error:
        return auth_error

    error = verify_provisioning_signature(request)
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
    has_spt = billing_result is not None
    if billing_result is False:
        _capture_provisioning_event(
            "update_service",
            "error",
            error_code="billing_activation_failed",
            service_id=service_id,
            team_id=team_id,
            has_spt=has_spt,
        )
        return _error_response(
            "billing_activation_failed",
            "Failed to activate billing with payment credentials",
            resource_id=resource_id,
        )

    if service_id == PAY_AS_YOU_GO_SERVICE_ID and billing_result is None:
        _capture_provisioning_event(
            "update_service", "error", error_code="requires_payment_credentials", service_id=service_id, team_id=team_id
        )
        return _error_response(
            "requires_payment_credentials", "Payment credentials required for paid plan", resource_id=resource_id
        )

    _set_provisioning_service_id(team, service_id)

    region = get_instance_region() or "US"
    host = _region_to_host(region)

    _capture_provisioning_event(
        "update_service",
        "success",
        service_id=service_id,
        team_id=team_id,
        has_spt=has_spt,
        billing_result=str(billing_result),
    )

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


# ---------------------------------------------------------------------------
# POST /provisioning/resources/:id/remove
# Detaches the resource from the orchestrator: removes it from the token's
# scope and clears provisioning metadata. Preserves the underlying team and
# user data so the customer can still access PostHog directly.
# ---------------------------------------------------------------------------


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@region_proxy(strategy="bearer_lookup")
def provisioning_resource_remove(request: Request, resource_id: str) -> Response:
    auth_error, user, access_token = _authenticate_bearer(request)
    if auth_error:
        return auth_error

    if error := _verify_hmac_if_present(request):
        return error
    if error := verify_api_version(request):
        return error

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

    scoped_teams = access_token.scoped_teams or []
    if team_id not in scoped_teams:
        return Response(
            {
                "status": "error",
                "id": resource_id,
                "error": {"code": "forbidden", "message": "Resource not accessible with this token"},
            },
            status=403,
        )

    from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

    try:
        TeamProvisioningConfig.objects.filter(team_id=team_id).delete()
    except Exception:
        capture_exception(additional_properties={"team_id": team_id, "step": "remove_provisioning_config"})
        _capture_provisioning_event("resource_removed", "error", team_id=team_id, error_code="remove_config_failed")
        return Response(
            {
                "status": "error",
                "id": resource_id,
                "error": {"code": "remove_failed", "message": "Failed to remove resource"},
            },
            status=500,
        )

    _remove_team_from_token_scopes(access_token, team_id)

    _capture_provisioning_event("resource_removed", "success", team_id=team_id)

    return Response({"status": "removed", "id": resource_id})


def _remove_team_from_token_scopes(access_token: OAuthAccessToken, team_id: int) -> None:
    remaining = [t for t in (access_token.scoped_teams or []) if t != team_id]

    # Atomic so a refresh token can never be left with the removed team still in
    # scope while the access token has it stripped — otherwise the orchestrator
    # could refresh and replay the removed team right back into scope.
    with transaction.atomic():
        refresh_tokens = OAuthRefreshToken.objects.filter(access_token=access_token)

        if not remaining:
            refresh_tokens.update(access_token=None, revoked=timezone.now(), scoped_teams=[])
            access_token.delete()
            return

        access_token.scoped_teams = remaining
        access_token.save(update_fields=["scoped_teams"])

        for rt in refresh_tokens:
            rt.scoped_teams = [t for t in (rt.scoped_teams or []) if t != team_id]
            rt.save(update_fields=["scoped_teams"])


def _resolve_resource_response(request: Request, resource_id: str) -> Response:
    auth_error, user, access_token = _authenticate_bearer(request)
    if auth_error:
        return auth_error

    if error := _verify_hmac_if_present(request):
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

    service_id = _get_provisioning_service_id(team)
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
@region_proxy(strategy="bearer_lookup")
def deep_links(request: Request) -> Response:
    auth_error, user, access_token = _authenticate_bearer(request)
    if auth_error:
        return auth_error

    # HMAC partners must include a valid signature on this endpoint - bearer alone
    # is not sufficient to mint a full web session via the deep-link primitive.
    if access_token.application.provisioning_auth_method == "hmac":
        if not request.META.get("HTTP_STRIPE_SIGNATURE"):
            return _error_response(
                "hmac_signature_required",
                "HMAC signature required for this partner",
                status=401,
            )
        if error := verify_provisioning_signature(request):
            return error
    elif error := _verify_hmac_if_present(request):
        return error

    if error := verify_api_version(request):
        return error

    if not access_token.application.provisioning_can_issue_deep_links:
        _capture_provisioning_event("deep_link_created", "not_enabled")
        return _error_response(
            "deep_links_not_enabled",
            "Deep links are not enabled for this partner",
            status=403,
        )

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


def _partner_label(partner: OAuthApplication | None) -> str:
    if not partner:
        return "Stripe"
    if partner.provisioning_partner_type:
        return partner.provisioning_partner_type.capitalize()
    if partner.name:
        return partner.name
    return "Stripe"


def _enforce_partner_rate_limit(partner: OAuthApplication, endpoint: str) -> Response | None:
    """Enforce per-partner rate limit using the model's override or a conservative default.

    Returns a 429 Response if the limit is exceeded, or None if the request is allowed.
    Setting the model field to 0 disables rate limiting for that endpoint.

    Uses a fixed-window counter keyed on partner id + window-of-epoch. A partner can
    burst up to 2x the limit across a window boundary (`limit` at :59:59 plus `limit`
    at :00:00); switch to a sliding window if that matters.
    """
    if endpoint not in PARTNER_RATE_LIMIT_DEFAULTS:
        raise ValueError(f"Unknown rate limit endpoint: {endpoint}")

    field_name = f"provisioning_rate_limit_{endpoint}"
    override = getattr(partner, field_name, None)

    if override is not None:
        limit = override
    else:
        limit = PARTNER_RATE_LIMIT_DEFAULTS.get(endpoint, 10)

    if limit <= 0:
        return None

    window_index = int(time.time()) // PARTNER_RATE_LIMIT_WINDOW_SECONDS
    cache_key = f"{PARTNER_RATE_LIMIT_PREFIX}{endpoint}:{partner.id}:{window_index}"

    try:
        cache.add(cache_key, 0, timeout=PARTNER_RATE_LIMIT_WINDOW_SECONDS)
        count = cache.incr(cache_key)
    except (ValueError, ConnectionError, TimeoutError) as e:
        logger.warning("partner_rate_limit_cache_error", endpoint=endpoint, partner_id=str(partner.id), error=str(e))
        # cache.add preserves any counter a concurrent request already initialized,
        # so a transient cache error doesn't reset the window for a partner at the limit.
        cache.add(cache_key, 1, timeout=PARTNER_RATE_LIMIT_WINDOW_SECONDS)
        count = 1

    if count > limit:
        event_name = PARTNER_RATE_LIMIT_EVENT_NAMES.get(endpoint, endpoint)
        _capture_provisioning_event(event_name, "rate_limited", partner_id=str(partner.id), limit=limit, count=count)
        retry_after = PARTNER_RATE_LIMIT_WINDOW_SECONDS - (int(time.time()) % PARTNER_RATE_LIMIT_WINDOW_SECONDS)
        response = Response(
            {
                "type": "error",
                "error": {
                    "code": "rate_limited",
                    "message": f"Rate limit exceeded for this partner ({endpoint}). Try again later.",
                },
            },
            status=429,
        )
        response["Retry-After"] = str(retry_after)
        return response
    return None


def _enforce_cimd_registration_throttle(request: Request) -> Response | None:
    """Rate-limit first-time CIMD app registration by IP and domain to match /authorize protections."""
    from posthog.api.oauth.cimd import CIMD_THROTTLE_CLASSES, is_cimd_client_id

    client_id = request.data.get("client_id") or request.query_params.get("client_id")
    if not is_cimd_client_id(client_id):
        return None
    if OAuthApplication.objects.filter(cimd_metadata_url=client_id).exists():
        return None

    for throttle_cls in CIMD_THROTTLE_CLASSES:
        throttle = throttle_cls()
        if not throttle.allow_request(request, view=None):  # type: ignore[arg-type]
            logger.warning("cimd_rate_limited", client_id=client_id, scope=throttle.scope, wait=throttle.wait())
            return Response(
                {
                    "type": "error",
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many new client registrations. Try again later.",
                    },
                },
                status=429,
            )

    if error := _enforce_cimd_domain_rate_limit(cast(str, client_id)):
        return error

    return None


def _enforce_cimd_domain_rate_limit(client_id: str) -> Response | None:
    """Prevent a single domain from registering unlimited CIMD apps via different URL paths."""
    from urllib.parse import urlparse

    domain = urlparse(client_id).hostname
    if not domain:
        return None

    window_index = int(time.time()) // CIMD_DOMAIN_RATE_LIMIT_WINDOW_SECONDS
    key = f"{CIMD_DOMAIN_RATE_LIMIT_PREFIX}{domain}:{window_index}"
    try:
        count = cache.incr(key)
    except ValueError:
        cache.add(key, 0, timeout=CIMD_DOMAIN_RATE_LIMIT_WINDOW_SECONDS)
        count = cache.incr(key)

    if count > CIMD_DOMAIN_RATE_LIMIT_MAX:
        logger.warning("cimd_domain_rate_limited", client_id=client_id, domain=domain, count=count)
        _capture_provisioning_event("account_request", "cimd_domain_rate_limited", domain=domain, count=count)
        return Response(
            {
                "type": "error",
                "error": {
                    "code": "rate_limited",
                    "message": "Too many new client registrations from this domain. Try again later.",
                },
            },
            status=429,
        )
    return None


def _verify_hmac_if_present(request: Request) -> Response | None:
    """Verify HMAC signature only if the Stripe-Signature header is present.

    For HMAC partners (Stripe), both HMAC + Bearer are required on resource endpoints.
    For non-HMAC partners (wizard, Bearer-only), skip HMAC and rely on Bearer auth alone.
    """
    if request.headers.get("stripe-signature"):
        return verify_provisioning_signature(request)
    return None


ALLOWED_PROVISIONING_SCOPES = {
    "customer_journey:read",
    "query:read",
    "conversation:read",
    "conversation:write",
    "experiment:read",
    "feature_flag:read",
    "insight:read",
    "organization:read",
    "person:read",
    "project:read",
    "ticket:read",
    "ticket:write",
    "user:read",
    "hog_flow:read",
    "hog_flow:write",
}


def _validate_scopes(scopes: list[str]) -> list[str] | None:
    """Validate scopes against the allowlist. Returns filtered scopes or None if any are invalid."""
    if not scopes:
        return scopes
    for scope in scopes:
        if scope not in ALLOWED_PROVISIONING_SCOPES:
            return None
    return scopes


def _error_response(code: str, message: str, resource_id: str = "", status: int = 400) -> Response:
    logger.warning("provisioning.error_response", code=code, message=message, resource_id=resource_id, status=status)
    return Response({"status": "error", "id": resource_id, "error": {"code": code, "message": message}}, status=status)


def _authenticate_bearer(request: Request) -> tuple[Response | None, Any, Any]:
    """Authenticate via Bearer token. Returns (error_response, user, access_token).

    Tries generic ProvisioningAuthentication first (any partner's token),
    then falls back to Stripe Projects HMAC auth.
    """

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return (_error_response("unauthorized", "Missing bearer token", status=401), None, None)

    token_value = auth_header[len("Bearer ") :].strip()
    if not token_value:
        return (_error_response("unauthorized", "Missing bearer token", status=401), None, None)

    access_token = find_oauth_access_token(token_value)
    if access_token is None:
        return (_error_response("unauthorized", "Invalid access token", status=401), None, None)

    if access_token.expires and access_token.expires < timezone.now():
        return (_error_response("unauthorized", "Access token expired", status=401), None, None)

    # Check if token belongs to any active provisioning partner's app
    app = access_token.application
    if app and app.is_provisioning_partner:
        if not app.provisioning_active:
            return (_error_response("unauthorized", "Partner is deactivated", status=401), None, None)
        if not app.provisioning_can_provision_resources:
            return (
                _error_response("forbidden", "Resource provisioning not enabled for this partner", status=403),
                None,
                None,
            )
        return None, access_token.user, access_token

    # Legacy fallback: accept tokens from the Stripe Projects app by client_id
    if app and app.client_id == settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID:
        return None, access_token.user, access_token

    return (_error_response("unauthorized", "Authentication failed", status=401), None, None)


def _get_legacy_stripe_oauth_app():
    if settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID:
        try:
            return OAuthApplication.objects.get(client_id=settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID)
        except OAuthApplication.DoesNotExist:
            logger.warning(
                "provisioning.oauth_app.client_id_not_found",
                client_id=settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID,
            )

    from oauthlib.common import generate_token

    return OAuthApplication.objects.create(
        name=LEGACY_STRIPE_APP_NAME,
        client_id=settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID or generate_token(),
        client_secret="",
        client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
        authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        redirect_uris="https://localhost",
        algorithm="RS256",
        provisioning_can_issue_deep_links=True,
    )


def _get_available_teams_for_user(user: User) -> list[dict[str, Any]]:
    """Return the user's non-demo teams for inclusion in the token exchange response."""
    org_ids = list(user.organization_memberships.values_list("organization_id", flat=True))
    teams = Team.objects.filter(organization_id__in=org_ids, is_demo=False).select_related("organization")
    return [
        {
            "id": team.id,
            "name": team.name,
            "organization_id": str(team.organization_id),
            "organization_name": team.organization.name if team.organization else "",
        }
        for team in teams
    ]


def _get_callback_url(partner_id: str) -> str:
    """Get the callback URL from the partner's redirect_uris, falling back to the Stripe setting."""
    if partner_id:
        try:
            app = OAuthApplication.objects.get(id=partner_id)
            redirect_uris = app.redirect_uris.strip()
            if redirect_uris:
                return redirect_uris.split()[0]
        except OAuthApplication.DoesNotExist:
            pass

    return settings.STRIPE_ORCHESTRATOR_CALLBACK_URL


def _get_oauth_app_for_code(code_data: dict):
    """Resolve the OAuthApplication for a token exchange.

    If the auth code was created by a provisioning partner, use that app.
    Otherwise fall back to the legacy Stripe Projects app lookup.
    """
    partner_id = code_data.get("partner_id", "")
    if partner_id:
        try:
            return OAuthApplication.objects.get(id=partner_id)
        except OAuthApplication.DoesNotExist:
            pass

    return _get_legacy_stripe_oauth_app()


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
