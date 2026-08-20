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
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
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
from ee.api.agentic_provisioning.wizard import (
    apply_provisioned_onboarding_flags,
    create_wizard_run,
    link_github_grant_to_team,
)


def partner_label(partner: OAuthApplication | None) -> str:
    """How a partner is named to a user, in the org it provisions and on the consent screen.

    The app's own name, which is what the user already saw when they authorized it.
    """
    if partner is None or not partner.name:
        return "Partner"
    return partner.name


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


def handle_existing_user(
    request_id: str,
    user: User,
    scopes: list[str],
    *,
    region: str,
    partner: OAuthApplication,
    code_challenge: str,
    code_challenge_method: str,
) -> dict[str, Any]:
    """Send an account request that matched an existing account to browser consent.

    Account-takeover defense: no partner may mint silently for an *existing* account, not
    even one with skip_existing_user_consent=True. A partner proves it controls itself (a
    verified client secret) or nothing at all (a public client_id), and neither is proof that
    it controls this email, so the user has to approve the link in a browser. This holds
    regardless of whether the user has reviewed their credentials: an unreviewed account is
    still a pre-existing account, and the email may belong to a direct signup that never
    touched provisioning, so silently linking it is the takeover.

    Consent also picks the project (see agentic_authorize), so nothing the partner sends can
    select a team for an account it did not create.
    """
    if partner.provisioning.skip_existing_user_consent:
        capture_provisioning_event(
            "account_request",
            "silent_blocked_existing_user",
            partner=partner,
        )

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
    partner: OAuthApplication,
    code_challenge: str,
    code_challenge_method: str,
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
                partner=partner,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
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

    # Attribute the bootstrap team to the creating partner. The row already exists
    # (the Team extension signal created it inside bootstrap), so this is an update.
    # Without it the mapping stays unclaimed, and resource removal treats unclaimed as
    # fair game for any partner whose token happens to scope the team.
    TeamProvisioningConfig.objects.filter(team_id=team.id, application__isnull=True).update(application=partner)

    # Every provisioned account is treated as already onboarded — apply the flags at
    # bootstrap so the account is covered regardless of which follow-up blocks (if any)
    # run, rather than only on the GitHub wizard path.
    apply_provisioned_onboarding_flags(user, team)

    # Emit the standard signup event so provisioned accounts flow into the shared
    # signup / activation / billing analyses, segmentable by client. Vercel does the
    # same (ee/vercel/integration.py); the agentic path previously skipped it entirely.
    report_user_signed_up(
        user,
        is_instance_first_user=False,
        is_organization_first_user=True,
        backend_processor="AgenticProvisioning",
        social_provider=partner.name,
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
    if isinstance(wizard_config, dict):
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
        partner_id=str(partner.id),
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
        # create_wizard_run refuses an ungranted partner anyway, but checking before the grant
        # is linked keeps a refused request from consuming a single-use grant the partner
        # would then have to mint again.
        if not partner.provisioning.can_start_wizard_runs:
            return {
                "error": {
                    "code": "forbidden",
                    "message": "Starting wizard runs is not enabled for this partner",
                }
            }

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
