"""Account-request handling: onboarding new users, linking existing ones, and
the browser consent detour for partners that can't skip it."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode

from django.core.cache import cache
from django.db import IntegrityError
from django.utils import timezone

from posthog.api.authentication import password_reset_token_generator
from posthog.event_usage import report_user_signed_up
from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthApplication
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.scopes import scopes_within_ceiling
from posthog.tasks.email import send_provisioning_welcome

from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.constants import (
    AUTH_CODE_CACHE_PREFIX,
    AUTH_CODE_TTL_SECONDS,
    PENDING_AUTH_CACHE_PREFIX,
    PENDING_AUTH_TTL_SECONDS,
)
from ee.api.agentic_provisioning.exceptions import ProvisioningError
from ee.api.agentic_provisioning.regions import region_to_host
from ee.api.agentic_provisioning.teams import resolve_team_for_existing_user
from ee.api.agentic_provisioning.wizard import create_wizard_run, link_github_grant_to_team


def partner_label(partner: OAuthApplication | None) -> str:
    if partner is None:
        return "Partner"
    if partner.provisioning_partner_type:
        return partner.provisioning_partner_type.capitalize()
    if partner.name:
        return partner.name
    return "Partner"


def get_callback_url(app: OAuthApplication | None) -> str | None:
    """Get the callback URL from the partner's redirect_uris.

    Returns None when the partner is gone or has no redirect URI registered;
    callers must fail the flow rather than redirect blindly.
    """
    if app is None:
        return None
    redirect_uris = app.redirect_uris.strip()
    if not redirect_uris:
        return None
    return redirect_uris.split()[0]


def mint_auth_code(
    *,
    user_id: int,
    org_id: str,
    team_id: int,
    partner_id: str,
    scopes: list[str],
    region: str,
    code_challenge: str,
    code_challenge_method: str,
) -> str:
    """Mint a single-use authorization code in the cache and return it."""
    code = secrets.token_urlsafe(32)
    cache.set(
        f"{AUTH_CODE_CACHE_PREFIX}{code}",
        {
            "issued_at": timezone.now().isoformat(),
            "user_id": user_id,
            "org_id": org_id,
            "team_id": team_id,
            "partner_id": partner_id,
            "scopes": scopes,
            "region": region,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        },
        timeout=AUTH_CODE_TTL_SECONDS,
    )
    return code


def mint_pending_auth_code(pending: dict[str, Any], *, user_id: int, org_id: str, team_id: int) -> str:
    """Mint an auth code carrying the parameters stored in a pending consent state."""
    return mint_auth_code(
        user_id=user_id,
        org_id=org_id,
        team_id=team_id,
        partner_id=pending.get("partner_id", ""),
        scopes=pending.get("scopes", []),
        region=pending.get("region", "US"),
        code_challenge=pending.get("code_challenge", ""),
        code_challenge_method=pending.get("code_challenge_method", "S256"),
    )


def build_authorize_url(confirmation_secret: str, scopes: list[str], region: str = "") -> str:
    # region_to_host falls back to SITE_URL for an unknown/empty region.
    base = region_to_host(region).rstrip("/")
    params = urlencode({"state": confirmation_secret, "scope": " ".join(scopes)})
    return f"{base}/api/agentic/authorize?{params}"


def caller_proved_existing_trust(partner: OAuthApplication, user: User, authenticated_user: User | None) -> bool:
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


def handle_existing_user(
    request_id: str,
    user: User,
    scopes: list[str],
    *,
    region: str,
    team_id: int | None,
    partner: OAuthApplication | None,
    code_challenge: str,
    code_challenge_method: str,
    authenticated_user: User | None,
) -> dict[str, Any]:
    # Account-takeover defense: a partner with skip_existing_user_consent=True may only mint
    # silently for an *existing* account when the caller proved a prior trust relationship with
    # that user (see caller_proved_existing_trust). Without proof we fall through to consent,
    # otherwise any caller could mint a code for an account they don't control. This holds
    # regardless of whether the user has reviewed their credentials: an unreviewed account is
    # still a pre-existing account, and the email may belong to a direct signup that never
    # touched provisioning — silently linking it is the takeover.
    silent_blocked = (
        partner is not None
        and partner.provisioning_skip_existing_user_consent
        and not caller_proved_existing_trust(partner, user, authenticated_user)
    )

    if silent_blocked:
        assert partner is not None  # implied by silent_blocked
        capture_provisioning_event(
            "account_request",
            "silent_blocked_existing_user",
            partner=partner,
        )

    if partner and (not partner.provisioning_skip_existing_user_consent or silent_blocked):
        if not code_challenge:
            raise ProvisioningError(
                "invalid_request", "code_challenge is required for public clients", request_id=request_id
            )
        if not scopes_within_ceiling(scopes, partner.ceiling_scopes):
            raise ProvisioningError(
                "invalid_scope",
                "One or more requested scopes exceed the application's allowed scopes",
                request_id=request_id,
            )
        return require_user_consent(
            request_id,
            user,
            scopes,
            region,
            partner,
            code_challenge,
            code_challenge_method,
        )

    team = resolve_team_for_existing_user(user, team_id)
    if team is None:
        capture_provisioning_event("account_request", "error", error_code="team_resolution_failed")
        raise ProvisioningError(
            "team_resolution_failed", "Could not resolve a project for this user", request_id=request_id
        )

    code = mint_auth_code(
        user_id=user.id,
        org_id=str(team.organization_id),
        team_id=team.id,
        partner_id=str(partner.id) if partner else "",
        scopes=scopes,
        region=region,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )

    capture_provisioning_event("account_request", "existing_user", partner=partner, region=region, team_id=team.id)

    return {"id": request_id, "type": "oauth", "oauth": {"code": code}}


def require_user_consent(
    request_id: str,
    user: User,
    scopes: list[str],
    region: str,
    partner: OAuthApplication,
    code_challenge: str,
    code_challenge_method: str,
) -> dict[str, Any]:
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

    auth_url = build_authorize_url(state, scopes, region=region)

    capture_provisioning_event("account_request", "requires_auth", partner=partner, region=region)

    return {
        "id": request_id,
        "type": "requires_auth",
        "requires_auth": {"url": auth_url},
    }


def handle_new_user(
    request_id: str,
    data: dict,
    email: str,
    scopes: list[str],
    *,
    region: str,
    partner: OAuthApplication | None,
    code_challenge: str,
    code_challenge_method: str,
    authenticated_user: User | None,
) -> dict[str, Any]:
    name = data.get("name", "")
    first_name = name.split(" ")[0] if name else ""

    configuration = data.get("configuration")
    if not isinstance(configuration, dict):
        configuration = {}

    label = partner_label(partner)
    org_name = configuration.get("organization_name") or f"{label} ({email})"

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
            capture_provisioning_event("account_request", "race_condition_existing_user", region=region)
            return handle_existing_user(
                request_id,
                existing,
                scopes,
                region=region,
                team_id=None,
                partner=partner,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                authenticated_user=authenticated_user,
            )
        capture_provisioning_event("account_request", "creation_failed", region=region)
        raise ProvisioningError(
            "account_creation_failed", "Failed to create account", request_id=request_id, status=500
        )

    capture_provisioning_event(
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
    wizard_repository: str | None = None
    if isinstance(wizard_config, dict) and partner is not None:
        wizard_payload = process_wizard_block(partner=partner, user=user, team=team, wizard_config=wizard_config)
        if "error" not in wizard_payload:
            wizard_repository = str(wizard_config.get("repository"))

    # Queued after the wizard block so the "we're setting up your repo" email only
    # sends once the run actually exists; the email still goes out (without the
    # repository paragraph) when the wizard block failed, since the account is real.
    try:
        reset_token = password_reset_token_generator.make_token(user)
        if wizard_repository:
            send_provisioning_welcome.delay(user.id, reset_token, label, repository=wizard_repository)
        else:
            send_provisioning_welcome.delay(user.id, reset_token, label)
    except Exception:
        capture_exception(additional_properties={"user_id": user.id, "step": "provisioning_welcome_email"})

    code = mint_auth_code(
        user_id=user.id,
        org_id=str(organization.id),
        team_id=team.id,
        partner_id=str(partner.id) if partner else "",
        scopes=scopes,
        region=region,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )

    response_body: dict[str, Any] = {"id": request_id, "type": "oauth", "oauth": {"code": code}}
    if wizard_payload is not None:
        response_body["wizard"] = wizard_payload
    return response_body


def process_wizard_block(*, partner: OAuthApplication, user: User, team: Team, wizard_config: dict) -> dict[str, Any]:
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

        link_github_grant_to_team(
            partner=partner,
            user=user,
            team=team,
            grant_id=str(grant_id),
            installation_id=str(installation_id),
        )

        run_payload = create_wizard_run(
            partner=partner,
            user_id=user.id,
            team=team,
            repository=str(repository),
            branch=str(wizard_config.get("branch") or "") or None,
        )
        return dict(run_payload)
    except ProvisioningError as exc:
        return {"error": {"code": exc.code, "message": exc.message}}
    except Exception:
        capture_exception(additional_properties={"team_id": team.id, "step": "account_requests_wizard_block"})
        return {"error": {"code": "run_creation_failed", "message": "Unexpected error starting the wizard run"}}


def resolve_pending_partner(partner_id: str) -> OAuthApplication | None:
    """Look up the partner referenced by a pending consent state; None when gone."""
    if not partner_id:
        return None
    try:
        return OAuthApplication.objects.get(id=partner_id)
    except OAuthApplication.DoesNotExist:
        return None
