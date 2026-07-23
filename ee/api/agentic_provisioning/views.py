from __future__ import annotations

import re
import time
import uuid
import base64
import hashlib
import secrets
import unicodedata
from datetime import datetime, timedelta
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
from django.utils.http import url_has_allowed_host_and_scheme

import requests
import structlog
import posthoganalytics
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import (
    AuthenticationFailed,
    ValidationError as DRFValidationError,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.authentication import password_reset_token_generator
from posthog.api.email_verification import EmailVerifier
from posthog.api.github_callback.team_services import link_github_installation_for_user
from posthog.event_usage import report_user_signed_up
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import GitHubInstallationAccessFetchError, GitHubIntegration, Integration
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken, find_oauth_access_token
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.user import OnboardingSkippedReason, User
from posthog.models.utils import (
    generate_random_oauth_access_token,
    generate_random_oauth_refresh_token,
    generate_random_token_personal,
    mask_key_value,
)
from posthog.rbac.user_access_control import UserAccessControl
from posthog.scopes import narrow_scopes_to_ceiling, scopes_within_ceiling
from posthog.tasks.email import send_provisioning_welcome
from posthog.utils import get_instance_region

from products.tasks.backend.facade import api as tasks_facade

from . import AUTH_CODE_CACHE_PREFIX, PENDING_AUTH_CACHE_PREFIX, github_grants
from .authentication import ProvisioningAuthentication
from .errors import error_response, typed_error_response
from .region_proxy import region_proxy

logger = structlog.get_logger(__name__)

AUTH_CODE_TTL_SECONDS = 300
PENDING_AUTH_TTL_SECONDS = 600
DEEP_LINK_TTL_SECONDS = 600
DEEP_LINK_CACHE_PREFIX = "provisioning_deep_link:"
DEEP_LINK_MAX_PATH_LENGTH = 2000
# Control chars, whitespace, and backslashes never appear in a legitimate in-app path; they are the
# building blocks of header-injection and backslash-host open-redirect tricks, so reject them outright.
DEEP_LINK_DISALLOWED_PATH_CHARS = re.compile(r"[\x00-\x20\x7f-\x9f\\]")
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
    "github_grants": 10,
    "wizard_runs": 20,
}
PARTNER_RATE_LIMIT_EVENT_NAMES: dict[str, str] = {
    "account_requests": "account_request",
    "token_exchanges": "token_exchange",
    "resource_creates": "resource_created",
    "github_grants": "github_grant",
    "wizard_runs": "wizard_run",
}

# Per-user wizard-run budget matching the session endpoint's limits (2/hour, 5/day), which
# can't run here — the partner path has no session user on the request. Unlike the session
# endpoint's throttles, which count only non-failed/non-cancelled runs from the DB, this is a
# plain request counter: failed runs still consume partner quota. Aligning it with the
# outcome-aware counting is a pending follow-up.
WIZARD_RUN_USER_RATE_LIMIT_PREFIX = "provisioning_wizard_run_user:"
WIZARD_RUN_USER_RATE_LIMITS: list[tuple[str, int, int]] = [
    ("burst", 2, 3600),
    ("day", 5, 86400),
]

# Repo-picker polling budget per grant (the website polls while the visitor installs the
# GitHub App in another tab). Keyed per grant, so one stuck visitor can't starve others.
GITHUB_GRANT_POLL_RATE_LIMIT_PREFIX = "provisioning_github_grant_poll:"
GITHUB_GRANT_POLL_RATE_LIMIT_MAX = 120
GITHUB_GRANT_POLL_RATE_LIMIT_WINDOW_SECONDS = 3600

_SAFE_STATE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,256}$")

# Mirrors PersonalAPIKey.label's CharField(max_length=40) - keep in sync if that ever changes.
PROVISIONED_PAT_LABEL_MAX_LENGTH = 40
# Cap partner-supplied prefix below the full label length so " - {team_name}" still
# survives the truncation. A 37-char prefix would otherwise consume the whole label
# and the team name would disappear from the truncated result.
PROVISIONED_PAT_LABEL_PREFIX_MAX_LENGTH = 25

ACCESS_TOKEN_EXPIRY_SECONDS = 365 * 24 * 3600
PARTNER_TOKEN_EXPIRY_SECONDS = 3600


# ---------------------------------------------------------------------------
# POST /provisioning/account_requests — onboard a new or existing user and
# return either an auth code (new user) or a redirect URL (existing user)
# ---------------------------------------------------------------------------


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@region_proxy(strategy="body_region")
def account_requests(request: Request) -> Response:

    if error := _enforce_cimd_registration_throttle(request):
        return error

    # --- Identify partner ---
    auth = ProvisioningAuthentication()
    partner = None
    authenticated_user = None
    try:
        result = auth.authenticate(request)
        if result:
            authenticated_user, partner = result
    except AuthenticationFailed:
        return typed_error_response("unauthorized", "Authentication failed", status=401)

    if partner is None and auth.cimd_registration_pending:
        return Response(
            {"type": "registering", "retry_after": 5},
            status=202,
        )

    if partner is None:
        return typed_error_response("unauthorized", "Authentication required", status=401)

    # --- Parse request ---
    data = request.data
    request_id = data.get("id", "")
    email = data.get("email")
    if not email:
        _capture_provisioning_event("account_request", "error", error_code="missing_email")
        return typed_error_response("invalid_request", "email is required")

    scopes = data.get("scopes", [])
    expires_at_str = data.get("expires_at", "")
    configuration = data.get("configuration") or {}

    if expires_at_str:
        from django.utils.dateparse import parse_datetime

        expires_at = parse_datetime(expires_at_str)
        if expires_at and expires_at < timezone.now():
            _capture_provisioning_event("account_request", "error", error_code="expired")
            return typed_error_response("expired", "Account request has expired")

    if not partner.provisioning_can_create_accounts:
        _capture_provisioning_event("account_request", "error", error_code="account_creation_disabled")
        return typed_error_response("forbidden", "Account creation is not enabled for this partner", status=403)

    if error := _enforce_partner_rate_limit(partner, "account_requests"):
        return error

    # PKCE: capture code_challenge for later verification
    code_challenge = data.get("code_challenge", "")
    code_challenge_method = data.get("code_challenge_method", "S256")
    if code_challenge and code_challenge_method != "S256":
        return typed_error_response("invalid_request", "Only S256 code_challenge_method is supported")
    if code_challenge and (
        len(code_challenge) < 43 or len(code_challenge) > 128 or not re.fullmatch(r"[A-Za-z0-9_\-]+", code_challenge)
    ):
        return typed_error_response(
            "invalid_request", "code_challenge must be 43-128 characters using base64url charset"
        )

    region = (configuration.get("region") or "US").upper()

    requested_team_id = configuration.get("team_id")
    if requested_team_id is not None:
        try:
            requested_team_id = int(requested_team_id)
        except (ValueError, TypeError):
            return typed_error_response(
                "invalid_request", "configuration.team_id must be an integer", request_id=request_id
            )

    existing_user = User.objects.filter(email=email).first()

    if existing_user:
        return _handle_existing_user(
            request_id,
            existing_user,
            scopes,
            region,
            requested_team_id,
            partner,
            code_challenge,
            code_challenge_method,
            authenticated_user,
        )

    return _handle_new_user(
        request_id,
        data,
        email,
        scopes,
        region,
        partner,
        code_challenge,
        code_challenge_method,
        authenticated_user,
    )


def _caller_proved_existing_trust(partner: OAuthApplication, user: User, authenticated_user: User | None) -> bool:
    """True only when the caller proved a prior trust relationship with this user.

    This is what lets a skip-consent partner re-mint silently for an existing user; without
    it the request falls through to browser consent. The proof differs by auth method:

    - Bearer callers present a single user-scoped access token. That token proves a
      relationship only with its own user, so it qualifies only when it belongs to the user
      being re-linked — otherwise any user of the partner could ride another user's live
      credential to mint a code for that account.
    - PKCE callers are public: the partner is identified solely by a client_id that anyone
      can send, so the request carries no proof the caller controls the partner. The "user
      already holds a live credential" signal proves nothing, so these never qualify.
    """
    if partner.provisioning_auth_method == "bearer":
        return authenticated_user is not None and authenticated_user.id == user.id
    return False


def _handle_existing_user(
    request_id: str,
    user: User,
    scopes: list[str],
    region: str = "US",
    team_id: int | None = None,
    partner: OAuthApplication | None = None,
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    authenticated_user: User | None = None,
) -> Response:
    # Account-takeover defense: a partner with skip_existing_user_consent=True may only mint
    # silently for an *existing* account when the caller proved a prior trust relationship with
    # that user (see _caller_proved_existing_trust). Without proof we fall through to consent,
    # otherwise any caller could mint a code for an account they don't control. This holds
    # regardless of whether the user has reviewed their credentials: an unreviewed account is
    # still a pre-existing account, and the email may belong to a direct signup that never
    # touched provisioning — silently linking it is the takeover.
    silent_blocked = (
        partner is not None
        and partner.provisioning_skip_existing_user_consent
        and not _caller_proved_existing_trust(partner, user, authenticated_user)
    )

    if silent_blocked:
        assert partner is not None  # implied by silent_blocked
        _capture_provisioning_event(
            "account_request",
            "silent_blocked_existing_user",
            partner=partner,
        )

    if partner and (not partner.provisioning_skip_existing_user_consent or silent_blocked):
        if not code_challenge:
            return typed_error_response(
                "invalid_request", "code_challenge is required for public clients", request_id=request_id
            )
        if not scopes_within_ceiling(scopes, partner.ceiling_scopes):
            return typed_error_response(
                "invalid_scope",
                "One or more requested scopes exceed the application's allowed scopes",
                request_id=request_id,
            )
        return _require_user_consent(
            request_id,
            user,
            scopes,
            region,
            partner,
            code_challenge,
            code_challenge_method,
        )

    team = _resolve_team_for_existing_user(user, team_id)
    if team is None:
        _capture_provisioning_event("account_request", "error", error_code="team_resolution_failed")
        return typed_error_response(
            "team_resolution_failed", "Could not resolve a project for this user", request_id=request_id
        )

    code = secrets.token_urlsafe(32)
    cache.set(
        f"{AUTH_CODE_CACHE_PREFIX}{code}",
        {
            "issued_at": timezone.now().isoformat(),
            "user_id": user.id,
            "org_id": str(team.organization_id),
            "team_id": team.id,
            "partner_id": str(partner.id) if partner else "",
            "scopes": scopes,
            "region": region,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        },
        timeout=AUTH_CODE_TTL_SECONDS,
    )

    _capture_provisioning_event("account_request", "existing_user", partner=partner, region=region, team_id=team.id)

    return Response({"id": request_id, "type": "oauth", "oauth": {"code": code}})


def _require_user_consent(
    request_id: str,
    user: User,
    scopes: list[str],
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
            "partner_id": str(partner.id),
            "partner_name": partner.name,
            "region": region,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            # We only reach consent because the partner could not skip it for this user, so
            # the authorize step must require it too — never silently auto-approve this state.
            "consent_required": True,
        },
        timeout=PENDING_AUTH_TTL_SECONDS,
    )

    auth_url = _build_authorize_url(state, scopes, region=region)

    _capture_provisioning_event("account_request", "requires_auth", partner=partner, region=region)

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
    region: str,
    partner: OAuthApplication | None = None,
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    authenticated_user: User | None = None,
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
            is_email_verified=False,
        )
    except IntegrityError:
        existing = User.objects.filter(email=email).first()
        if existing:
            _capture_provisioning_event("account_request", "race_condition_existing_user", region=region)
            return _handle_existing_user(
                request_id,
                existing,
                scopes,
                region,
                None,
                partner,
                code_challenge,
                code_challenge_method,
                authenticated_user,
            )
        _capture_provisioning_event("account_request", "creation_failed", region=region)
        return typed_error_response(
            "account_creation_failed", "Failed to create account", request_id=request_id, status=500
        )

    _capture_provisioning_event(
        "account_request",
        "new_user",
        partner=partner,
        region=region,
        team_id=team.id,
    )

    # Emit the standard signup event so provisioned accounts flow into the shared
    # signup / activation / billing analyses, segmentable by client. Vercel does the
    # same (ee/vercel/integration.py); the agentic path previously skipped it entirely.
    report_user_signed_up(
        user,
        is_instance_first_user=False,
        is_organization_first_user=True,
        backend_processor="AgenticProvisioning",
        social_provider=partner.name if partner else "",
        user_analytics_metadata=user.get_analytics_metadata(),
        org_analytics_metadata=organization.get_analytics_metadata(),
    )

    # Optional drop-flow wizard block: link the GitHub grant to the bootstrap team and
    # enqueue a cloud wizard run in the same call. A wizard failure never fails the
    # request — the account exists, so the partner gets the account plus a structured
    # wizard.error and retries via the granular resource actions. Partners that don't
    # send a wizard block are unaffected (no wizard key, unchanged email behavior).
    # Grants are region-local, so this request must hit the region that minted the grant.
    wizard_config = configuration.get("wizard")
    wizard_payload: dict[str, Any] | None = None
    if isinstance(wizard_config, dict) and partner is not None:
        wizard_payload = _process_wizard_block(partner=partner, user=user, team=team, wizard_config=wizard_config)

    # Queued after the wizard block so the "we're setting up your repo" email only
    # sends once the run actually exists; the email still goes out (without the
    # repository paragraph) when the wizard block failed, since the account is real.
    try:
        reset_token = password_reset_token_generator.make_token(user)
        wizard_repository: str | None = None
        if wizard_payload is not None and "error" not in wizard_payload and isinstance(wizard_config, dict):
            wizard_repository = str(wizard_config.get("repository"))
        if wizard_repository:
            send_provisioning_welcome.delay(user.id, reset_token, partner_label, repository=wizard_repository)
        else:
            send_provisioning_welcome.delay(user.id, reset_token, partner_label)
    except Exception:
        capture_exception(additional_properties={"user_id": user.id, "step": "provisioning_welcome_email"})

    code = secrets.token_urlsafe(32)
    cache_key = f"{AUTH_CODE_CACHE_PREFIX}{code}"
    cache.set(
        cache_key,
        {
            "issued_at": timezone.now().isoformat(),
            "user_id": user.id,
            "org_id": str(organization.id),
            "team_id": team.id,
            "partner_id": str(partner.id) if partner else "",
            "scopes": scopes,
            "region": region,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        },
        timeout=AUTH_CODE_TTL_SECONDS,
    )

    response_body: dict[str, Any] = {"id": request_id, "type": "oauth", "oauth": {"code": code}}
    if wizard_payload is not None:
        response_body["wizard"] = wizard_payload
    return Response(response_body)


def _process_wizard_block(*, partner: OAuthApplication, user: User, team: Team, wizard_config: dict) -> dict[str, Any]:
    """Run the bundled drop flow for a freshly bootstrapped account: link the GitHub
    grant to the team, then enqueue the cloud wizard run.

    Never raises — returns either the run payload ({task_id, run_id, status}) or
    {"error": {code, message}} for the partner to branch on and retry granularly.
    """
    try:
        grant_id = wizard_config.get("grant_id")
        installation_id = wizard_config.get("installation_id")
        repository = wizard_config.get("repository")
        if not grant_id or not installation_id or not repository:
            return {
                "error": {
                    "code": "invalid_request",
                    "message": "wizard requires grant_id, installation_id and repository",
                }
            }

        error, _integration, _already_linked = _link_github_grant_to_team(
            partner=partner,
            user=user,
            team=team,
            grant_id=str(grant_id),
            installation_id=str(installation_id),
        )
        if error is not None:
            return {"error": error.data.get("error", {"code": "invalid_request", "message": "GitHub link failed"})}

        error, run_payload = _create_wizard_run(
            partner=partner,
            user_id=user.id,
            team=team,
            repository=str(repository),
            branch=str(wizard_config.get("branch") or "") or None,
        )
        if error is not None:
            return {
                "error": error.data.get(
                    "error", {"code": "run_creation_failed", "message": "Failed to start the wizard run"}
                )
            }
        assert run_payload is not None
        return dict(run_payload)
    except Exception:
        capture_exception(additional_properties={"team_id": team.id, "step": "account_requests_wizard_block"})
        return {"error": {"code": "run_creation_failed", "message": "Unexpected error starting the wizard run"}}


def _build_authorize_url(confirmation_secret: str, scopes: list[str], region: str = "") -> str:
    base = _region_to_host(region).rstrip("/") if region else settings.SITE_URL.rstrip("/")
    params = urlencode({"state": confirmation_secret, "scope": " ".join(scopes)})
    return f"{base}/api/agentic/authorize?{params}"


# ---------------------------------------------------------------------------
# POST /provisioning/github/grants
# GET  /provisioning/github/grants/:grant_id/repositories
# GitHub grants for drop-style partner flows: the partner forwards a GitHub OAuth
# code, we exchange and hold the user tokens server-side, and the partner only
# ever sees an opaque grant_id. No region proxy: grants are region-local (the
# partner must call the region that minted the grant).
# ---------------------------------------------------------------------------


def _authenticate_provisioning_partner(request: Request) -> tuple[Response | None, OAuthApplication | None]:
    """Identify a provisioning partner, requiring proof-bearing auth.
    Returns (error_response, partner).

    Only Bearer partners carry proof that the caller controls the partner.
    PKCE partners are identified solely by a public ``client_id`` anyone can send, so
    they never qualify for these endpoints — they exchange GitHub OAuth codes and read
    back GitHub account metadata, which must sit behind a real partner trust boundary.
    """
    auth = ProvisioningAuthentication()
    try:
        result = auth.authenticate(request)
    except AuthenticationFailed:
        result = None
    partner = result[1] if result else None
    if partner is None:
        return (
            typed_error_response("unauthorized", "Authentication required", status=401),
            None,
        )
    if partner.provisioning_auth_method != "bearer":
        return (
            typed_error_response("forbidden", "This endpoint requires a confidential partner", status=403),
            None,
        )
    return None, partner


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def github_grants_create(request: Request) -> Response:

    auth_error, partner = _authenticate_provisioning_partner(request)
    if auth_error or partner is None:
        return auth_error or Response(status=401)

    if not partner.provisioning_can_create_accounts:
        _capture_provisioning_event("github_grant", "error", partner=partner, error_code="account_creation_disabled")
        return typed_error_response("forbidden", "Account creation is not enabled for this partner", status=403)

    if error := _enforce_partner_rate_limit(partner, "github_grants"):
        return error

    code = request.data.get("code")
    redirect_uri = request.data.get("redirect_uri") or None
    if not code or not isinstance(code, str):
        _capture_provisioning_event("github_grant", "error", partner=partner, error_code="missing_code")
        return typed_error_response("invalid_request", "code is required")

    try:
        authorization = GitHubIntegration.github_user_from_code(code, redirect_uri=redirect_uri)
    except requests.RequestException:
        # Network failure or a non-JSON GitHub error body raising through .json() — retryable,
        # distinct from a clean "bad code" exchange failure (which returns None below).
        _capture_provisioning_event("github_grant", "error", partner=partner, error_code="github_unavailable")
        return typed_error_response("github_unavailable", "GitHub request failed", status=502)
    if authorization is None:
        _capture_provisioning_event("github_grant", "error", partner=partner, error_code="github_exchange_failed")
        return typed_error_response("github_exchange_failed", "Could not exchange the GitHub OAuth code", status=502)

    # A user with no verified email gets a grant with email=null — the partner
    # collects an email inline instead. Only an access refusal (App permission
    # misconfiguration) hard-fails, so it can't masquerade as that user state.
    try:
        email = github_grants.fetch_primary_email(authorization.access_token)
    except github_grants.GitHubEmailAccessDenied:
        _capture_provisioning_event("github_grant", "error", partner=partner, error_code="email_unavailable")
        return typed_error_response("email_unavailable", "GitHub denied reading the user's email addresses", status=502)
    except requests.RequestException:
        _capture_provisioning_event("github_grant", "error", partner=partner, error_code="github_unavailable")
        return typed_error_response("github_unavailable", "GitHub request failed", status=502)

    grant = github_grants.create_grant(partner, authorization, email)
    _capture_provisioning_event("github_grant", "created", partner=partner, gh_login=grant.gh_login)
    return Response(
        {
            "grant_id": grant.grant_id,
            "gh_login": grant.gh_login,
            "email": grant.email,
            "expires_in": github_grants.GITHUB_GRANT_TTL_SECONDS,
        }
    )


def _enforce_grant_poll_rate_limit(grant_id: str) -> Response | None:
    window_index = int(time.time()) // GITHUB_GRANT_POLL_RATE_LIMIT_WINDOW_SECONDS
    key = f"{GITHUB_GRANT_POLL_RATE_LIMIT_PREFIX}{grant_id}:{window_index}"
    try:
        cache.add(key, 0, timeout=GITHUB_GRANT_POLL_RATE_LIMIT_WINDOW_SECONDS)
        count = cache.incr(key)
    except (ValueError, ConnectionError, TimeoutError):
        count = 1
    if count > GITHUB_GRANT_POLL_RATE_LIMIT_MAX:
        response = typed_error_response(
            "rate_limited", "Too many repository listing requests for this grant", status=429
        )
        response["Retry-After"] = str(
            GITHUB_GRANT_POLL_RATE_LIMIT_WINDOW_SECONDS
            - (int(time.time()) % GITHUB_GRANT_POLL_RATE_LIMIT_WINDOW_SECONDS)
        )
        return response
    return None


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def github_grant_repositories(request: Request, grant_id: str) -> Response:

    auth_error, partner = _authenticate_provisioning_partner(request)
    if auth_error or partner is None:
        return auth_error or Response(status=401)

    grant = github_grants.load_grant(grant_id, partner)
    if grant is None:
        return typed_error_response("grant_not_found", "Grant not found or expired", status=404)

    if error := _enforce_grant_poll_rate_limit(grant_id):
        return error

    try:
        listing = github_grants.list_installations_and_repositories(grant.access_token)
    except requests.RequestException:
        _capture_provisioning_event("github_grant", "listing_failed", partner=partner)
        return typed_error_response("github_unavailable", "GitHub request failed", status=502)

    return Response({"gh_login": grant.gh_login, **listing})


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
        mismatch_params = urlencode(
            {
                "expected_email": pending["email"],
                "current_email": request.user.email,
                "partner_name": pending.get("partner_name", ""),
                "state": state,
            }
        )
        return HttpResponseRedirect(f"{settings.SITE_URL.rstrip('/')}/agentic/account-mismatch?{mismatch_params}")

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
    is_trusted_partner = False
    if partner_id:
        try:
            partner_app = OAuthApplication.objects.get(id=partner_id)
            if not partner_app.provisioning_active:
                cache.delete(pending_key)
                _capture_provisioning_event("authorize", "partner_deactivated")
                return HttpResponseRedirect(f"{settings.SITE_URL}?error=partner_deactivated")
            # Fail closed: a partner-identified pending state missing the flag (e.g. created by an
            # older pod mid-deploy) must still require consent, never silently auto-approve.
            is_trusted_partner = partner_app.provisioning_skip_existing_user_consent and not pending.get(
                "consent_required", True
            )
        except OAuthApplication.DoesNotExist:
            pass

    if is_trusted_partner and len(memberships) == 1 and len(non_demo_teams) == 1:
        organization = memberships[0].organization
        team = non_demo_teams[0]

        callback_url = _get_callback_url(pending.get("partner_id", ""))
        if callback_url is None:
            _capture_provisioning_event("authorize", "missing_callback")
            return HttpResponseRedirect(f"{settings.SITE_URL}?error=missing_callback")

        code = secrets.token_urlsafe(32)
        cache.set(
            f"{AUTH_CODE_CACHE_PREFIX}{code}",
            {
                "issued_at": timezone.now().isoformat(),
                "user_id": user.id,
                "org_id": str(organization.id),
                "team_id": team.id,
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
    confirm_partner: OAuthApplication | None = None
    if confirm_partner_id:
        try:
            confirm_partner = OAuthApplication.objects.get(id=confirm_partner_id)
            if not confirm_partner.provisioning_active:
                cache.delete(pending_key)
                _capture_provisioning_event("authorize_confirm", "partner_deactivated", partner=confirm_partner)
                return Response({"error": "partner_deactivated"}, status=403)
        except OAuthApplication.DoesNotExist:
            pass

    callback_url = _get_callback_url(pending.get("partner_id", ""))
    if callback_url is None:
        _capture_provisioning_event("authorize_confirm", "missing_callback", partner=confirm_partner)
        return Response({"error": "missing_callback"}, status=400)

    code = secrets.token_urlsafe(32)
    # Set auth code BEFORE deleting pending state so a cache hiccup
    # between the two doesn't leave the user with no recovery path.
    cache.set(
        f"{AUTH_CODE_CACHE_PREFIX}{code}",
        {
            "issued_at": timezone.now().isoformat(),
            "user_id": user.id,
            "org_id": str(team.organization_id),
            "team_id": team.id,
            "partner_id": pending.get("partner_id", ""),
            "scopes": pending.get("scopes", []),
            "region": pending.get("region", "US"),
            "code_challenge": pending.get("code_challenge", ""),
            "code_challenge_method": pending.get("code_challenge_method", "S256"),
        },
        timeout=AUTH_CODE_TTL_SECONDS,
    )
    cache.delete(pending_key)

    sanitized_state = re.sub(r"[^A-Za-z0-9_\-]", "", state)
    params = urlencode({"code": code, "state": sanitized_state})
    redirect_url = f"{callback_url}?{params}"

    _capture_provisioning_event("authorize_confirm", "success", partner=confirm_partner, team_id=team_id)

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


def _lock_application(application_id: uuid.UUID) -> OAuthApplication | None:
    """Row-lock the OAuthApplication so direct-mint serializes with revoke_application_sessions.

    The revoke updates this row first and holds the lock for its whole transaction before
    sweeping tokens, so a mint that takes the same lock is forced into one of two safe orders:
    it holds the lock and its new tokens land before the revoke's sweep (which then catches
    them), or the revoke committed first and the caller reads the now-visible
    `sessions_revoked_at` and rejects. Must be called inside `transaction.atomic()`.
    """
    return OAuthApplication.objects.select_for_update().filter(pk=application_id).first()


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

    # Auth check: every code requires PKCE verification. All verification happens
    # BEFORE cache.delete so a failed attempt doesn't consume the code.
    stored_challenge = code_data.get("code_challenge", "")
    if not stored_challenge:
        _capture_provisioning_event("token_exchange", "missing_code_challenge", grant_type="authorization_code")
        return Response({"error": "invalid_request", "error_description": "Authentication required"}, status=401)

    code_verifier = request.data.get("code_verifier", "")
    if not code_verifier:
        _capture_provisioning_event("token_exchange", "missing_code_verifier", grant_type="authorization_code")
        return Response(
            {"error": "invalid_request", "error_description": "code_verifier is required for PKCE"}, status=401
        )
    computed = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    )
    if computed != stored_challenge:
        _capture_provisioning_event("token_exchange", "pkce_mismatch", grant_type="authorization_code")
        return Response(
            {"error": "invalid_grant", "error_description": "PKCE code_verifier does not match"}, status=400
        )

    # Consume the code before rate limiting so a leaked auth code can't be replayed
    # to burn the partner's bucket. Auth codes are single-use by spec, so the
    # tradeoff (rate-limited client loses the code) is acceptable — clients can
    # re-initiate the OAuth flow if rate-limited.
    cache.delete(cache_key)

    oauth_app: OAuthApplication | None = None
    partner_id = code_data.get("partner_id", "")
    if partner_id:
        try:
            oauth_app = OAuthApplication.objects.get(id=partner_id)
        except (OAuthApplication.DoesNotExist, ValidationError, ValueError):
            logger.warning("token_exchange_app_missing", partner_id=partner_id)
    if oauth_app is None:
        _capture_provisioning_event("token_exchange", "oauth_app_missing", grant_type="authorization_code")
        return Response(
            {"error": "invalid_grant", "error_description": "Unknown application for this authorization code"},
            status=400,
        )

    if error := _enforce_partner_rate_limit(oauth_app, "token_exchanges"):
        return error

    user_id = code_data["user_id"]
    team_id = code_data["team_id"]
    scopes = code_data.get("scopes", [])

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        _capture_provisioning_event("token_exchange", "user_not_found", grant_type="authorization_code")
        return Response({"error": "invalid_grant", "error_description": "User not found"}, status=400)

    # Lock the app row before reading the revoke stamp and minting, so this serializes
    # with revoke_application_sessions (see _lock_application). Provisioning auth codes
    # live in the cache, not OAuthGrant, so the revoke's sweep can't reach them — the
    # `issued_at` carried on the code is what a revoke is checked against. Codes minted
    # before `issued_at` shipped lack the field; fail closed (they expire in
    # AUTH_CODE_TTL_SECONDS and the client can re-run the flow).
    with transaction.atomic():
        locked_app = _lock_application(oauth_app.pk)
        sessions_revoked_at = locked_app.sessions_revoked_at if locked_app else None
        if sessions_revoked_at is not None:
            issued_at_raw = code_data.get("issued_at")
            issued_at = datetime.fromisoformat(issued_at_raw) if issued_at_raw else None
            if issued_at is None or issued_at < sessions_revoked_at:
                _capture_provisioning_event("token_exchange", "sessions_revoked", grant_type="authorization_code")
                return Response(
                    {"error": "invalid_grant", "error_description": "Application sessions were revoked; re-authorize."},
                    status=400,
                )

        # Direct-mint bypasses /authorize's OAuthValidator, so the per-app scope
        # ceiling has to be enforced here before the token is created by hand.
        app_scopes = locked_app.ceiling_scopes if locked_app else []
        # A request with no explicit scopes gets the app's full ceiling.
        requested_scopes = scopes if scopes else app_scopes
        if not scopes_within_ceiling(requested_scopes, app_scopes):
            _capture_provisioning_event("token_exchange", "scope_ceiling_exceeded", grant_type="authorization_code")
            return Response(
                {
                    "error": "invalid_scope",
                    "error_description": "Requested scopes exceed the application's allowed scopes",
                },
                status=400,
            )
        scope_str = " ".join(requested_scopes)

        token_expiry = (
            PARTNER_TOKEN_EXPIRY_SECONDS
            if oauth_app and oauth_app.is_provisioning_partner
            else ACCESS_TOKEN_EXPIRY_SECONDS
        )

        scoped_teams = _compute_partner_scoped_teams(oauth_app, user, team_id)
        # A partner token carries its restriction in scoped_teams alone, and the standard
        # OAuth permission check treats an empty scoped_teams as unrestricted (permissions.py).
        # _compute_partner_scoped_teams returns [] exactly when the base team is gone or the
        # user lost access, so minting here would hand out a project-unrestricted bearer.
        # Fail closed and force re-authorization.
        if not scoped_teams:
            _capture_provisioning_event("token_exchange", "no_accessible_teams", grant_type="authorization_code")
            return Response(
                {
                    "error": "invalid_grant",
                    "error_description": "No accessible teams for this authorization; re-authorize.",
                },
                status=400,
            )

        access_token_value = generate_random_oauth_access_token(None)
        access_token = OAuthAccessToken.objects.create(
            application=oauth_app,
            token=access_token_value,
            user=user,
            expires=timezone.now() + timedelta(seconds=token_expiry),
            scope=scope_str,
            scoped_teams=scoped_teams,
        )

        refresh_token_value = generate_random_oauth_refresh_token(None)
        OAuthRefreshToken.objects.create(
            application=oauth_app,
            token=refresh_token_value,
            user=user,
            access_token=access_token,
            scoped_teams=scoped_teams,
        )

    account_id = str(code_data.get("org_id", ""))

    available_teams = _get_available_teams_for_user(user)

    _capture_provisioning_event(
        "token_exchange",
        "success",
        partner=oauth_app,
        grant_type="authorization_code",
        team_id=team_id,
        user_id=user.id,
        granted_team_count=len(scoped_teams),
    )

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

    # Lock the app row first (revoke_application_sessions locks it before sweeping tokens),
    # then re-read the refresh token under that lock, so the rotate-and-mint serializes with
    # the revoke: either we hold the lock and our new tokens land before its sweep, or it
    # committed first and we see the token already revoked (or the stamp) and reject. Looking
    # the app up by id first (without locking the token row) keeps the lock order app→token,
    # matching the revoke, so the two can't deadlock.
    with transaction.atomic():
        application_id = (
            OAuthRefreshToken.objects.filter(token=refresh_token_value, revoked__isnull=True)
            .values_list("application_id", flat=True)
            .first()
        )
        locked_app = _lock_application(application_id) if application_id else None
        old_refresh = (
            OAuthRefreshToken.objects.select_related("user", "access_token")
            .filter(token=refresh_token_value, revoked__isnull=True)
            .first()
        )
        if old_refresh is None:
            _capture_provisioning_event("token_exchange", "invalid_refresh_token", grant_type="refresh_token")
            return Response(
                {"error": "invalid_grant", "error_description": "Invalid or revoked refresh token"}, status=400
            )

        oauth_app = locked_app
        user = old_refresh.user
        old_scoped_teams = old_refresh.scoped_teams or []
        # base_team_id at refresh: the first team in the prior scope. The consent team
        # (authorized at grant time) has the lowest id and sorts first at issuance;
        # partner-provisioned teams are always created later, so they take higher ids
        # and are only ever appended after it. [0] is therefore the consent team. This
        # ordering is load-bearing: _compute_partner_scoped_teams re-adds the consent
        # team only when it is base_team_id (it has no TeamProvisioningConfig for this
        # app), so a lower-id provisioned team becoming [0] would silently drop the
        # consent team from the refreshed scope. If the prior token was somehow empty-
        # scoped, fall back to zero so the helper short-circuits without claiming a team.
        base_team_id = old_scoped_teams[0] if old_scoped_teams else 0
        scoped_teams = _compute_partner_scoped_teams(oauth_app, user, base_team_id)
        # Same fail-closed rule as issuance: an empty scoped_teams is unrestricted under the
        # standard permission check, so a refresh whose base team vanished or whose access was
        # revoked must re-authorize rather than rotate into a project-unrestricted token.
        # Checked before any token row is mutated so a rejected refresh never revokes the
        # caller's only token.
        if not scoped_teams:
            _capture_provisioning_event("token_exchange", "no_accessible_teams", grant_type="refresh_token")
            return Response(
                {"error": "invalid_grant", "error_description": "No accessible teams for this token; re-authorize."},
                status=400,
            )
        # A rotated-away access token leaves no scope to carry over; the refreshed
        # token gets an empty scope rather than inheriting anything implicit.
        old_scope = old_refresh.access_token.scope if old_refresh.access_token else ""

        sessions_revoked_at = locked_app.sessions_revoked_at if locked_app else None
        if sessions_revoked_at is not None and old_refresh.created < sessions_revoked_at:
            _capture_provisioning_event("token_exchange", "sessions_revoked", grant_type="refresh_token")
            return Response(
                {"error": "invalid_grant", "error_description": "Application sessions were revoked; re-authorize."},
                status=400,
            )

        # Cap the refreshed scope at the app's current ceiling before touching any
        # token rows — a since-tightened ceiling must drop the removed scopes, and a
        # token now fully outside the ceiling has to re-authorize rather than refresh.
        # Done up front so a rejected refresh never revokes the caller's only token.
        app_scopes = oauth_app.ceiling_scopes if oauth_app else []
        narrowed_scopes = narrow_scopes_to_ceiling(old_scope.split(), app_scopes)
        if narrowed_scopes is None:
            _capture_provisioning_event("token_exchange", "scope_ceiling_exceeded", grant_type="refresh_token")
            return Response(
                {
                    "error": "invalid_grant",
                    "error_description": "Token scopes are no longer within the application's allowed scopes; re-authorize.",
                },
                status=400,
            )
        new_scope = " ".join(narrowed_scopes)

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
            PARTNER_TOKEN_EXPIRY_SECONDS
            if oauth_app and oauth_app.is_provisioning_partner
            else ACCESS_TOKEN_EXPIRY_SECONDS
        )

        new_access_value = generate_random_oauth_access_token(None)
        new_access = OAuthAccessToken.objects.create(
            application=oauth_app,
            token=new_access_value,
            user=user,
            expires=timezone.now() + timedelta(seconds=token_expiry),
            scope=new_scope,
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

    _capture_provisioning_event(
        "token_exchange",
        "success",
        partner=oauth_app,
        grant_type="refresh_token",
        team_id=base_team_id,
        user_id=user.id if user else None,
        granted_team_count=len(scoped_teams),
    )

    return Response(
        {
            "token_type": "bearer",
            "access_token": new_access_value,
            "refresh_token": new_refresh_value,
            "expires_in": token_expiry,
        }
    )


class _InvalidLabelPrefixError(Exception):
    """Raised when a partner-supplied label_prefix fails validation."""


def _extract_label_prefix(request: Request) -> str | None:
    """Extract and validate the optional ``label_prefix`` from the request body.

    Returns ``None`` when the field is absent or empty (caller creates an
    unprefixed label). Raises ``_InvalidLabelPrefixError`` when the field is
    present but malformed (wrong type, too long, or contains control or format
    characters that would render badly in the user's PAT list).
    """
    raw = request.data.get("label_prefix")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise _InvalidLabelPrefixError("label_prefix must be a string")

    stripped = raw.strip()
    if not stripped:
        return None

    if len(stripped) > PROVISIONED_PAT_LABEL_PREFIX_MAX_LENGTH:
        raise _InvalidLabelPrefixError(
            f"label_prefix must be {PROVISIONED_PAT_LABEL_PREFIX_MAX_LENGTH} characters or fewer"
        )

    # Reject Unicode control (Cc), format (Cf), and line/paragraph separators (Zl/Zp).
    # Cf is the important one - it includes bidi overrides (U+202A-U+202E) and
    # isolates (U+2066-U+2069), which a partner could use to re-order surrounding
    # text in the user's settings page (Trojan Source class). Cc covers C0 + DEL.
    if any(unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} for c in stripped):
        raise _InvalidLabelPrefixError("label_prefix must not contain control or format characters")

    return stripped


def _maybe_create_provisioned_pat(
    user: User, team: Team, app: OAuthApplication | None, granted_scope: str | None, label_prefix: str | None = None
) -> str | None:
    """Create a Personal API Key for a provisioned user and return the raw key value.

    Gated by ``app.provisioning_issues_personal_api_key``: off by default, so most
    apps never receive a provisioned PAT (the OAuth token is the credential).
    Returns ``None`` when the gate is off, and the caller omits ``personal_api_key``
    from the response entirely.

    When enabled (the grandfathered legacy Stripe app), the key carries the granted
    OAuth token's scopes (``granted_scope``) narrowed to the app's current ceiling,
    so a provisioned PAT can exceed neither what the user granted nor what the app
    may hold. Minting from the ceiling alone would hand out optional scopes the
    grant never included. A flag-on app with an unseeded ceiling mints nothing: an
    empty-scope PAT fails every scope check, and widening to a wildcard would
    bypass the ceiling.

    scoped_teams is set to [team.id] so the PAT only grants access to the team
    being provisioned, matching the scoping of the OAuth token issued in the
    same flow. Without this, a provisioning call from an existing user would
    return a PAT that reaches across every team the user already belongs to.

    ``label_prefix`` should be pre-validated by ``_extract_label_prefix``; pass
    ``None`` (or any falsy value) to label the key with just the team name.
    """
    if not app or not app.provisioning_issues_personal_api_key:
        return None
    if not app.ceiling_scopes:
        _capture_provisioning_event("pat_mint", "skipped_unseeded_ceiling", partner=app, team_id=team.id)
        return None
    granted = (granted_scope or "").split()
    if "*" in granted:
        # A legacy wildcard token covers everything, so the ceiling is the cap.
        pat_scopes = app.ceiling_scopes
    else:
        pat_scopes = narrow_scopes_to_ceiling([s for s in granted if ":" in s], app.ceiling_scopes) or []
    if not pat_scopes:
        _capture_provisioning_event("pat_mint", "skipped_no_granted_scopes", partner=app, team_id=team.id)
        return None
    try:
        api_key_value = generate_random_token_personal()
        label_base = f"{label_prefix} - {team.name}" if label_prefix else team.name
        # PersonalAPIKey.label is stored as a CharField(max_length=40); cap the
        # final string to match so we never violate the column constraint.
        label = label_base[:PROVISIONED_PAT_LABEL_MAX_LENGTH]

        PersonalAPIKey.objects.create(
            user=user,
            label=label,
            secure_value=hash_key_value(api_key_value),
            mask_value=mask_key_value(api_key_value),
            scopes=pat_scopes,
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
    existing = (
        TeamProvisioningConfig.objects.filter(
            stripe_project_id=project_id,
            application=access_token.application,
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
            defaults={"stripe_project_id": project_id, "application": access_token.application},
        )
    except IntegrityError:
        new_team.delete()
        race_winner = (
            TeamProvisioningConfig.objects.filter(
                stripe_project_id=project_id,
                application=access_token.application,
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


def _compute_partner_scoped_teams(
    application: OAuthApplication | None,
    user: User,
    base_team_id: int,
) -> list[int]:
    """Compute the durable scope for a partner OAuth token at issuance/refresh.

    Returns the set of every team where ``TeamProvisioningConfig.application ==
    application`` (i.e. this partner provisioned the team for this user, attributed
    at create time) AND the team lives in the same organization as ``base_team_id``
    AND the user still has team-level access. This is partner-agnostic, not
    Stripe-specific: ``stripe_project_id`` is the (legacily named) external project
    id every partner sets, always written alongside ``application`` in
    ``_resolve_or_create_project_team``, so the ``application`` filter already
    implies a provisioned team. The organization filter pins the token to the
    authorization context:
    a partner with OAuth grants in multiple orgs for the same user must not be
    able to reach an org-B team via an org-A token just because the user happens
    to be a member of both.

    Returns ``[]`` when ``application`` is None (legacy refresh tokens with no
    app binding). A partner-unattributed token cannot be safely scoped, so it
    gets no teams and the holder must re-authorize. Falling through would let
    ``filter(application=None)`` match every TPC row with NULL application
    across every partner.

    Returns ``[]`` if ``base_team_id`` no longer resolves to a team the user
    can access; stale scope must not grant ongoing access after ACL revocation
    or org removal.
    """
    if application is None:
        return []

    try:
        base_team = Team.objects.select_related("organization").get(id=base_team_id)
    except Team.DoesNotExist:
        return []
    if not _user_can_access_team(user, base_team):
        return []

    candidate_team_ids = set(
        TeamProvisioningConfig.objects.filter(
            application=application,
            team__organization_id=base_team.organization_id,
        ).values_list("team_id", flat=True)
    )
    candidate_team_ids.add(base_team_id)

    granted: set[int] = {base_team_id}
    other_teams = Team.objects.select_related("organization").filter(
        id__in=candidate_team_ids - {base_team_id},
    )
    for team in other_teams:
        if _user_can_access_team(user, team):
            granted.add(team.id)

    # sorted() only for deterministic test assertions and log diffs; scope order is not a correctness requirement
    return sorted(granted)


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

    app = access_token.application
    if app and app.provisioning_partner_type:
        if error := _enforce_partner_rate_limit(app, "resource_creates"):
            # Resource endpoints use {"status": "error"} envelope, not {"type": "error"}
            retry_after = error["Retry-After"] if "Retry-After" in error else "3600"
            response = error_response(
                "rate_limited", "Rate limit exceeded for this partner. Try again later.", status=429
            )
            response["Retry-After"] = retry_after
            return response

    try:
        label_prefix = _extract_label_prefix(request)
    except _InvalidLabelPrefixError as exc:
        _capture_provisioning_event("resource_created", "error", partner=app, error_code="invalid_label_prefix")
        return error_response("invalid_label_prefix", str(exc))

    scoped_teams = access_token.scoped_teams or []

    if not scoped_teams:
        _capture_provisioning_event("resource_created", "error", partner=app, error_code="no_team")
        return error_response("no_team", "No team associated with this token")

    project_id = request.data.get("project_id", "")
    configuration = request.data.get("configuration") or {}

    if project_id:
        try:
            team, scoped_teams = _resolve_or_create_project_team(
                project_id, scoped_teams, user, configuration, access_token
            )
        except _ProjectIdCollisionError:
            _capture_provisioning_event(
                "resource_created", "error", partner=app, error_code="project_id_conflict", project_id=project_id
            )
            return error_response(
                "project_id_conflict",
                "Project ID already linked to another organization",
                status=409,
            )
        if team is None:
            _capture_provisioning_event(
                "resource_created", "error", partner=app, error_code="not_found", project_id=project_id
            )
            return error_response("not_found", "Resource not found", status=404)
    else:
        team_id = scoped_teams[0]
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            _capture_provisioning_event(
                "resource_created", "error", partner=app, error_code="team_not_found", team_id=team_id
            )
            return error_response("team_not_found", "Team not found", resource_id=str(team_id), status=404)

    region = get_instance_region() or "US"
    host = _region_to_host(region)

    _capture_provisioning_event(
        "resource_created",
        "success",
        partner=app,
        team_id=team.id,
    )

    access_configuration: dict[str, str] = {
        "api_key": team.api_token,
        "host": host,
    }
    if personal_api_key := _maybe_create_provisioned_pat(
        user, team, access_token.application, access_token.scope, label_prefix=label_prefix
    ):
        access_configuration["personal_api_key"] = personal_api_key

    return Response(
        {
            "status": "complete",
            "id": str(team.id),
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

    try:
        label_prefix = _extract_label_prefix(request)
    except _InvalidLabelPrefixError as exc:
        _capture_provisioning_event("credential_rotation", "error", error_code="invalid_label_prefix")
        return error_response("invalid_label_prefix", str(exc), resource_id=resource_id)

    scoped_teams = access_token.scoped_teams or []

    try:
        team_id = int(resource_id)
    except (ValueError, TypeError):
        return error_response("invalid_resource_id", "Invalid resource ID", resource_id=resource_id)

    if team_id not in scoped_teams:
        return error_response(
            "forbidden", "Resource not accessible with this token", resource_id=resource_id, status=403
        )

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return error_response("not_found", "Resource not found", resource_id=resource_id, status=404)

    try:
        # Bearer flow resolves the token outside DRF, so read impersonation off the token directly.
        team.reset_token_and_save(user=user, is_impersonated_session=access_token.impersonated_by_id is not None)
    except Exception:
        capture_exception(additional_properties={"team_id": team_id})
        _capture_provisioning_event("credential_rotation", "failed", team_id=team_id)
        return error_response(
            "credential_rotation_failed", "Failed to rotate credentials", resource_id=resource_id, status=500
        )

    _capture_provisioning_event("credential_rotation", "success", team_id=team_id)

    region = get_instance_region() or "US"
    host = _region_to_host(region)

    access_configuration: dict[str, str] = {
        "api_key": team.api_token,
        "host": host,
    }
    if personal_api_key := _maybe_create_provisioned_pat(
        user, team, access_token.application, access_token.scope, label_prefix=label_prefix
    ):
        access_configuration["personal_api_key"] = personal_api_key

    return Response(
        {
            "status": "complete",
            "id": resource_id,
            "complete": {
                "access_configuration": access_configuration,
            },
        }
    )


# ---------------------------------------------------------------------------
# POST /provisioning/resources/:id/github_integration
# POST /provisioning/resources/:id/wizard_runs
# Drop-flow resource actions: link a GitHub installation to the team from a
# stored grant, then kick off a cloud wizard run against a repository.
# ---------------------------------------------------------------------------


def _drf_validation_error_code(exc: DRFValidationError) -> str | None:
    codes = exc.get_codes()
    if isinstance(codes, list) and codes:
        return str(codes[0])
    if isinstance(codes, str):
        return codes
    return None


def _apply_provisioned_onboarding_flags(user: User, team: Team) -> None:
    """Keep the app from routing a partner-provisioned account into onboarding on first
    login. Only applied to unclaimed accounts (never logged in, no password set) so an
    existing user going through the consent path keeps their onboarding state."""
    # Bootstrapped accounts store password="" (create_user skips set_password when the
    # password is None), which Django counts as *usable* — treat it as no password.
    has_password = bool(user.password) and user.has_usable_password()
    if user.last_login is not None or has_password:
        return
    if user.onboarding_skipped_at is None:
        user.onboarding_skipped_at = timezone.now()
    user.onboarding_skipped_reason = OnboardingSkippedReason.PROVISIONED
    user.onboarding_skipped_organization_id = team.organization_id
    user.save(
        update_fields=["onboarding_skipped_at", "onboarding_skipped_reason", "onboarding_skipped_organization_id"]
    )
    if not team.completed_snippet_onboarding:
        team.completed_snippet_onboarding = True
        team.save(update_fields=["completed_snippet_onboarding"])


def _link_github_grant_to_team(
    *, partner: OAuthApplication, user: User, team: Team, grant_id: str, installation_id: str
) -> tuple[Response | None, Integration | None, bool]:
    """Shared core of the github_integration action and the account_requests wizard
    block: validate the grant, verify installation ownership, create both GitHub
    records, consume the grant. Returns (error_response, integration, already_linked).
    """
    grant = github_grants.load_grant(grant_id, partner)
    if grant is None:
        # Idempotent retry: the grant is consumed on success, so a retry after a lost
        # response must not fail if the installation is already linked to this team.
        existing = Integration.objects.first_github_for_team_installation(team.id, str(installation_id))
        if existing is not None:
            # Re-apply onboarding flags idempotently: the grant is consumed as the last step,
            # so a crash between consume and the flag write would otherwise leave them unset
            # on a retry (this branch runs only once the grant is already gone).
            _apply_provisioned_onboarding_flags(user, team)
            return None, existing, True
        _capture_provisioning_event("github_integration", "error", partner=partner, error_code="grant_not_found")
        return (
            error_response("grant_not_found", "Grant not found or expired", resource_id=str(team.id), status=404),
            None,
            False,
        )

    try:
        integration = link_github_installation_for_user(
            user=user, team_id=team.id, installation_id=str(installation_id), authorization=grant.to_authorization()
        )
    except DRFValidationError as exc:
        code = _drf_validation_error_code(exc)
        if code == "installation_access_denied":
            _capture_provisioning_event("github_integration", "error", partner=partner, error_code=code)
            return (
                error_response(
                    "installation_access_denied",
                    "The GitHub user does not have access to this installation",
                    resource_id=str(team.id),
                    status=403,
                ),
                None,
                False,
            )
        if code == "installation_verify_failed":
            _capture_provisioning_event("github_integration", "error", partner=partner, error_code=code)
            return (
                error_response(
                    "installation_verify_failed",
                    "Could not verify installation access with GitHub",
                    resource_id=str(team.id),
                    status=502,
                ),
                None,
                False,
            )
        _capture_provisioning_event("github_integration", "error", partner=partner, error_code="invalid_request")
        return (
            error_response("invalid_request", str(exc.detail), resource_id=str(team.id), status=400),
            None,
            False,
        )
    except GitHubInstallationAccessFetchError:
        _capture_provisioning_event(
            "github_integration", "error", partner=partner, error_code="integration_creation_failed"
        )
        return (
            error_response(
                "integration_creation_failed",
                "Could not create the GitHub integration",
                resource_id=str(team.id),
                status=502,
            ),
            None,
            False,
        )

    github_grants.consume_grant(grant_id)
    _apply_provisioned_onboarding_flags(user, team)
    _capture_provisioning_event("github_integration", "success", partner=partner, team_id=team.id)
    return None, integration, False


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@region_proxy(strategy="bearer_lookup")
def provisioning_github_integration(request: Request, resource_id: str) -> Response:
    auth_error, user, access_token = _authenticate_bearer(request)
    if auth_error:
        return auth_error

    try:
        team_id = int(resource_id)
    except (ValueError, TypeError):
        return error_response("invalid_resource_id", "Invalid resource ID", resource_id=resource_id)

    if team_id not in (access_token.scoped_teams or []):
        return error_response(
            "forbidden", "Resource not accessible with this token", resource_id=resource_id, status=403
        )

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return error_response("not_found", "Resource not found", resource_id=resource_id, status=404)

    grant_id = request.data.get("grant_id")
    installation_id = request.data.get("installation_id")
    if not grant_id or not installation_id:
        return error_response("invalid_request", "grant_id and installation_id are required", resource_id=resource_id)

    error, integration, already_linked = _link_github_grant_to_team(
        partner=access_token.application,
        user=user,
        team=team,
        grant_id=str(grant_id),
        installation_id=str(installation_id),
    )
    if error:
        return error
    assert integration is not None

    return Response(
        {
            "status": "complete",
            "id": resource_id,
            "github_integration": {
                "integration_id": str(integration.id),
                "gh_login": (integration.config or {}).get("connecting_user_github_login"),
                "already_linked": already_linked,
            },
        }
    )


def _enforce_wizard_run_user_rate_limit(user_id: int) -> Response | None:
    """Cache-counter equivalent of the session cloud_run endpoint's per-user throttles;
    shared across the granular wizard_runs action and the bundled account_requests path
    so retries can't double-spend the budget."""
    for label, limit, window_seconds in WIZARD_RUN_USER_RATE_LIMITS:
        window_index = int(time.time()) // window_seconds
        key = f"{WIZARD_RUN_USER_RATE_LIMIT_PREFIX}{label}:{user_id}:{window_index}"
        try:
            cache.add(key, 0, timeout=window_seconds)
            count = cache.incr(key)
        except (ValueError, ConnectionError, TimeoutError):
            count = 1
        if count > limit:
            response = Response(
                {
                    "status": "error",
                    "error": {"code": "rate_limited", "message": "Too many wizard runs for this user. Try later."},
                },
                status=429,
            )
            response["Retry-After"] = str(window_seconds - (int(time.time()) % window_seconds))
            return response
    return None


def _create_wizard_run(
    *, partner: OAuthApplication, user_id: int, team: Team, repository: str, branch: str | None
) -> tuple[Response | None, dict[str, str] | None]:
    """Gate + throttle + create a cloud wizard run. Returns (error_response, run_payload)."""
    if not bool(settings.WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID):
        _capture_provisioning_event("wizard_run", "error", partner=partner, error_code="wizard_unavailable")
        return (
            error_response(
                "wizard_unavailable",
                "Running the setup wizard in the cloud is not available",
                resource_id=str(team.id),
                status=503,
            ),
            None,
        )

    repository = (repository or "").strip()
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        return (
            error_response("invalid_request", "repository must be in 'owner/repo' format", resource_id=str(team.id)),
            None,
        )

    if error := _enforce_wizard_run_user_rate_limit(user_id):
        return error, None
    if error := _enforce_partner_rate_limit(partner, "wizard_runs"):
        return error, None

    # Verifying the grant user owns the installation doesn't prove the installation can
    # reach the requested repo — a valid grant for one installation could otherwise report
    # wizard success for an owner/repo it can't operate on. Fail fast instead (after the
    # rate limits, so this GitHub call can't be used as an unthrottled probe).
    if GitHubIntegration.first_for_team_repository(team.id, repository, source="integration") is None:
        _capture_provisioning_event(
            "wizard_run", "error", partner=partner, error_code="github_integration_required", team_id=team.id
        )
        return (
            error_response(
                "github_integration_required",
                "The team does not have a GitHub integration that can access this repository",
                resource_id=str(team.id),
                status=400,
            ),
            None,
        )

    try:
        created = tasks_facade.create_wizard_cloud_run(
            team=team, user_id=user_id, repository=repository, branch=branch or None
        )
    except ValueError:
        # The facade raises when the team has no usable GitHub integration.
        _capture_provisioning_event(
            "wizard_run", "error", partner=partner, error_code="github_integration_required", team_id=team.id
        )
        return (
            error_response(
                "github_integration_required",
                "The team does not have a GitHub integration that can access this repository",
                resource_id=str(team.id),
                status=400,
            ),
            None,
        )
    except Exception:
        capture_exception(additional_properties={"team_id": team.id, "step": "provisioning_wizard_run"})
        _capture_provisioning_event(
            "wizard_run", "error", partner=partner, error_code="run_creation_failed", team_id=team.id
        )
        return (
            error_response(
                "run_creation_failed", "Failed to start the wizard run", resource_id=str(team.id), status=500
            ),
            None,
        )

    run = created.latest_run
    _capture_provisioning_event("wizard_run", "success", partner=partner, team_id=team.id, task_id=str(created.task_id))
    return None, {
        "task_id": str(created.task_id),
        "run_id": str(run.id) if run else "",
        "status": str(run.status) if run else "queued",
    }


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@region_proxy(strategy="bearer_lookup")
def provisioning_wizard_runs(request: Request, resource_id: str) -> Response:
    auth_error, user, access_token = _authenticate_bearer(request)
    if auth_error:
        return auth_error

    try:
        team_id = int(resource_id)
    except (ValueError, TypeError):
        return error_response("invalid_resource_id", "Invalid resource ID", resource_id=resource_id)

    if team_id not in (access_token.scoped_teams or []):
        return error_response(
            "forbidden", "Resource not accessible with this token", resource_id=resource_id, status=403
        )

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return error_response("not_found", "Resource not found", resource_id=resource_id, status=404)

    repository = request.data.get("repository")
    if not repository:
        return error_response("invalid_request", "repository is required", resource_id=resource_id)

    error, run_payload = _create_wizard_run(
        partner=access_token.application,
        user_id=user.id,
        team=team,
        repository=str(repository),
        branch=request.data.get("branch") or None,
    )
    if error:
        return error

    return Response({"status": "complete", "id": resource_id, "wizard_run": run_payload})


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

    try:
        # Clear the mapping only if it is unclaimed or owned by the caller's
        # application; an in-scope partner must not delete another partner's
        # provisioning mapping for the same team.
        config = TeamProvisioningConfig.objects.filter(team_id=team_id).first()
        if config is not None and config.application_id in (None, access_token.application_id):
            config.delete()
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
    """Strip ``team_id`` from every access/refresh token for this partner+user combo.

    Removing a resource has to revoke access for any *other* live token the same
    partner installation might be holding for the same user (e.g. a separate
    bearer issued via a prior OAuth grant that still has the team in scope).
    Touching only the calling ``access_token`` would let the partner continue
    operating on the team via a sibling token after `remove` returned, since
    operational endpoints accept any team currently in ``scoped_teams``.

    Atomic so a refresh token can never be left with the removed team still in
    scope while the access token has it stripped — otherwise the orchestrator
    could refresh and replay the removed team right back into scope.
    """
    application = access_token.application
    user = access_token.user
    if application is None or user is None:
        # Defensive: a provisioning bearer token without an app/user shouldn't
        # exist in practice, but fall back to the single-token strip if it does.
        application_filter: dict[str, object] = {"pk": access_token.pk}
        user_filter: dict[str, object] = {}
    else:
        application_filter = {"application": application, "user": user}
        user_filter = {"application": application, "user": user}

    with transaction.atomic():
        access_tokens = list(
            OAuthAccessToken.objects.select_for_update()
            .filter(scoped_teams__contains=[team_id], **application_filter)
            .order_by("pk")
        )
        for at in access_tokens:
            remaining = [t for t in (at.scoped_teams or []) if t != team_id]
            refresh_tokens = OAuthRefreshToken.objects.select_for_update().filter(access_token=at)
            if not remaining:
                refresh_tokens.update(access_token=None, revoked=timezone.now(), scoped_teams=[])
                at.delete()
                continue
            at.scoped_teams = remaining
            at.save(update_fields=["scoped_teams"])
            for rt in refresh_tokens:
                rt.scoped_teams = [t for t in (rt.scoped_teams or []) if t != team_id]
                rt.save(update_fields=["scoped_teams"])

        if user_filter:
            # Orphan refresh tokens (where the access token was already rotated
            # or deleted) still carry scope. Strip the team from those too.
            orphan_refresh = OAuthRefreshToken.objects.select_for_update().filter(
                scoped_teams__contains=[team_id],
                access_token__isnull=True,
                revoked__isnull=True,
                **user_filter,
            )
            for rt in orphan_refresh:
                rt.scoped_teams = [t for t in (rt.scoped_teams or []) if t != team_id]
                rt.save(update_fields=["scoped_teams"])


def _resolve_resource_response(request: Request, resource_id: str) -> Response:
    auth_error, user, access_token = _authenticate_bearer(request)
    if auth_error:
        return auth_error

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

    region = get_instance_region() or "US"
    host = _region_to_host(region)

    return Response(
        {
            "status": "complete",
            "id": resource_id,
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

    if not access_token.application.provisioning_can_issue_deep_links:
        _capture_provisioning_event("deep_link_created", "not_enabled", partner=access_token.application)
        return error_response(
            "deep_links_not_enabled",
            "Deep links are not enabled for this partner",
            status=403,
        )

    # `purpose` is a free-form label retained for analytics. `path` is the generic
    # destination: any in-app path the partner wants the user to land on after login.
    purpose = request.data.get("purpose", "dashboard")
    path = request.data.get("path")
    if path and not _is_safe_deep_link_path(path):
        _capture_provisioning_event(
            "deep_link_created", "invalid_path", partner=access_token.application, purpose=purpose
        )
        return error_response(
            "invalid_path",
            "path must be a relative in-app path beginning with a single '/'",
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
            "path": path or None,
        },
        timeout=DEEP_LINK_TTL_SECONDS,
    )

    expires_at = timezone.now() + timedelta(seconds=DEEP_LINK_TTL_SECONDS)

    url = f"{host}/agentic/login?token={token}"
    if team_id:
        url += f"&team_id={team_id}"

    _capture_provisioning_event(
        "deep_link_created", "success", partner=access_token.application, purpose=purpose, team_id=team_id
    )

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
    if partner is None:
        return "Partner"
    if partner.provisioning_partner_type:
        return partner.provisioning_partner_type.capitalize()
    if partner.name:
        return partner.name
    return "Partner"


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
        _capture_provisioning_event(event_name, "rate_limited", partner=partner, limit=limit, count=count)
        retry_after = PARTNER_RATE_LIMIT_WINDOW_SECONDS - (int(time.time()) % PARTNER_RATE_LIMIT_WINDOW_SECONDS)
        response = typed_error_response(
            "rate_limited", f"Rate limit exceeded for this partner ({endpoint}). Try again later.", status=429
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
            return typed_error_response(
                "rate_limited", "Too many new client registrations. Try again later.", status=429
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
        return typed_error_response(
            "rate_limited", "Too many new client registrations from this domain. Try again later.", status=429
        )
    return None


def _authenticate_bearer(request: Request) -> tuple[Response | None, Any, Any]:
    """Authenticate via Bearer token issued to an active provisioning partner.

    Returns (error_response, user, access_token).
    """

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return (error_response("unauthorized", "Missing bearer token", status=401), None, None)

    token_value = auth_header[len("Bearer ") :].strip()
    if not token_value:
        return (error_response("unauthorized", "Missing bearer token", status=401), None, None)

    access_token = find_oauth_access_token(token_value)
    if access_token is None:
        return (error_response("unauthorized", "Invalid access token", status=401), None, None)

    if access_token.expires and access_token.expires < timezone.now():
        return (error_response("unauthorized", "Access token expired", status=401), None, None)

    # Check if token belongs to any active provisioning partner's app
    app = access_token.application
    if app and app.is_provisioning_partner:
        if not app.provisioning_active:
            return (error_response("unauthorized", "Partner is deactivated", status=401), None, None)
        if not app.provisioning_can_provision_resources:
            return (
                error_response("forbidden", "Resource provisioning not enabled for this partner", status=403),
                None,
                None,
            )
        return None, access_token.user, access_token

    return (error_response("unauthorized", "Authentication failed", status=401), None, None)


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


def _get_callback_url(partner_id: str) -> str | None:
    """Get the callback URL from the partner's redirect_uris.

    Returns None when the partner cannot be resolved or has no redirect URI
    registered; callers must fail the flow rather than redirect blindly.
    """
    if not partner_id:
        return None
    try:
        app = OAuthApplication.objects.get(id=partner_id)
    except OAuthApplication.DoesNotExist:
        return None
    redirect_uris = app.redirect_uris.strip()
    if not redirect_uris:
        return None
    return redirect_uris.split()[0]


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
    path = link_data.get("path")

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

    # Deep-link login has no password challenge and no SSO step, so partner-asserted
    # email ownership is the only thing standing between an attacker and a session.
    # Require explicit is_email_verified=True - don't trust the legacy None passthrough
    # or the org-level email-verification-disabled flag.
    if user.is_email_verified is not True:
        try:
            EmailVerifier.create_token_and_send_email_verification(user)
        except Exception:
            # Intentionally swallowed: the login must stay blocked regardless of email delivery.
            # EmailVerifier captures the exception internally; the verify_email page has a resend button.
            logger.warning("agentic_login.verification_email_failed", user_id=user.id)
        _capture_deep_link_event("email_unverified", user_id=user_id)
        logger.warning("agentic_login.email_unverified", user_id=user_id)
        return HttpResponseRedirect(f"/verify_email/{user.uuid}")

    auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    _capture_deep_link_event("success", user_id=user_id, team_id=team_id, purpose=purpose)
    logger.info("agentic_login.success", user_id=user_id, team_id=team_id, purpose=purpose)

    redirect_path = _deep_link_redirect_path(purpose, team_id, path)
    return HttpResponseRedirect(redirect_path)


def _is_safe_deep_link_path(path: object) -> bool:
    """Allow only relative, same-origin in-app paths so a deep link can't become an open redirect."""
    return (
        isinstance(path, str)
        and 0 < len(path) <= DEEP_LINK_MAX_PATH_LENGTH
        # Reject control chars, whitespace, and backslashes (the `/\` backslash-host form included).
        and not DEEP_LINK_DISALLOWED_PATH_CHARS.search(path)
        and path.startswith("/")
        # Reject protocol-relative (`//`) forms; a single leading `/` keeps it same-origin.
        and not path.startswith("//")
        and url_has_allowed_host_and_scheme(path, allowed_hosts=None)
    )


def _deep_link_redirect_path(purpose: str, team_id: int | None, path: str | None = None) -> str:
    if path and _is_safe_deep_link_path(path):
        return path
    if path:
        # Unreachable in normal operation (mint-time validation already ran); a hit here means
        # cache tampering or a mint-side regression.
        logger.warning("agentic_login.unsafe_path_in_cache", path=path)
    if team_id and Team.objects.filter(id=team_id).exists():
        return f"/project/{team_id}"
    return "/"


def _capture_provisioning_event(
    event_type: str,
    outcome: str,
    *,
    partner: OAuthApplication | None = None,
    **extra: object,
) -> None:
    team_id = extra.get("team_id")
    distinct_id = f"agentic_provisioning_team_{team_id}" if team_id else f"agentic_provisioning_{uuid.uuid4().hex[:16]}"
    properties: dict[str, object] = {"outcome": outcome, **extra}
    if partner is not None:
        properties.setdefault("partner_id", str(partner.id))
        properties.setdefault("client_name", partner.name)
        if partner.provisioning_partner_type:
            properties.setdefault("partner_type", partner.provisioning_partner_type)
    posthoganalytics.capture(
        f"agentic_provisioning {event_type}",
        distinct_id=distinct_id,
        properties=properties,
    )


def _capture_deep_link_event(outcome: str, **extra: object) -> None:
    _capture_provisioning_event("deep link login", outcome, partner=None, **extra)
