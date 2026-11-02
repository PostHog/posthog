"""Account-request handling: onboarding new users, linking existing ones, and
the browser consent detour for partners that can't skip it."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from posthog.api.authentication import password_reset_token_generator
from posthog.api.signup import SIGNUP_BLOCKED_DETAIL, signup_refused
from posthog.event_usage import report_user_signed_up
from posthog.exceptions_capture import capture_exception
from posthog.helpers.email_utils import EmailLookupHandler
from posthog.models.oauth import OAuthApplication
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_provisioning import OrganizationProvisioning, get_billing_lock_partner
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.user import OnboardingSkippedReason, User
from posthog.scopes import scopes_within_ceiling
from posthog.tasks.email import send_provisioning_welcome

from products.security.backend.facade.api import REFUSAL_CODE as SECURITY_REFUSAL_CODE

from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.constants import (
    AUTH_CODE_CACHE_PREFIX,
    AUTH_CODE_TTL_SECONDS,
    PENDING_AUTH_CACHE_PREFIX,
    PENDING_AUTH_TTL_SECONDS,
)
from ee.api.agentic_provisioning.exceptions import ProvisioningError
from ee.api.agentic_provisioning.regions import region_to_host
from ee.api.agentic_provisioning.tokens import user_can_access_team


def partner_label(partner: OAuthApplication | None) -> str:
    """How a partner is named to a user, in the org it provisions and on the consent screen.

    The app's own name, which is what the user already saw when they authorized it.
    """
    if partner is None or not partner.name:
        return "Partner"
    return partner.name


def partner_organization_name(partner: OAuthApplication | None, email: str, requested: object = None) -> str:
    name = requested if isinstance(requested, str) and requested else f"{partner_label(partner)} ({email})"
    # Organization.name is a varchar(64), so a longer name would fail the insert.
    return name[:64]


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
    select a team for an account it did not create. For a partner that pays for its customers,
    consent picks no project: see get_or_create_partner_organization_team.
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


def find_partner_organization(user: User, partner: OAuthApplication) -> Organization | None:
    # Owned, not just joined: an admin or member of someone else's partner organization would
    # otherwise put this partner's project, and the partner's bill for it, in that organization.
    candidates = (
        Organization.objects.filter(
            partner_provisioning__application=partner,
            membership__user=user,
            membership__level=OrganizationMembership.Level.OWNER,
        )
        .exclude(is_active=False)
        .exclude(is_pending_deletion=True)
        .order_by("created_at", "id")
    )
    # The billing lock is the source of truth for whether the partner still pays: an organization
    # that pays for itself now, or that left the partner, must not take a new partner project.
    return next(
        (organization for organization in candidates if get_billing_lock_partner(organization) == partner),
        None,
    )


def find_partner_team(user: User, partner: OAuthApplication, organization: Organization) -> Team | None:
    # Only a project the partner provisioned, so reusing an organization never gives the
    # partner a project that a user created there.
    configs = (
        TeamProvisioningConfig.objects.filter(application=partner, team__organization=organization, team__is_demo=False)
        .exclude(team__project__is_pending_deletion=True)
        .select_related("team")
        .order_by("team_id")
    )
    return next((config.team for config in configs if user_can_access_team(user, config.team)), None)


class PartnerOrganizationChanged(Exception):
    pass


def get_or_create_partner_organization_team(
    user: User, partner: OAuthApplication, approved_organization_id: str | None
) -> tuple[Team, bool]:
    """Billing works per organization, so the project of a partner that pays for its customers
    must not go in one of the user's own organizations, where the user would pay for the
    partner's usage. It goes in an organization the partner pays for: one the user already
    owns, or a new one.

    approved_organization_id is the organization the consent page showed, or None when it showed
    a new one.
    """
    with transaction.atomic():
        # Serializes one user's consents, so two concurrent confirms cannot both miss the
        # organization or project that the other one is creating and each create one.
        locked_user = User.objects.select_for_update(no_key=True).get(pk=user.pk)
        organization = find_partner_organization(locked_user, partner)
        if (str(organization.id) if organization is not None else None) != approved_organization_id:
            raise PartnerOrganizationChanged
        if organization is not None:
            team = find_partner_team(locked_user, partner, organization)
            if team is None:
                team = Team.objects.create_with_data(initiating_user=locked_user, organization=organization)
                TeamProvisioningConfig.objects.create(team=team, application=partner)
            return team, False

        previous_organization_id = locked_user.current_organization_id
        previous_team_id = locked_user.current_team_id
        organization, _, team = Organization.objects.bootstrap(
            locked_user, name=partner_organization_name(partner, locked_user.email)
        )
        # bootstrap makes the new organization current. Switching back keeps `@current` in the
        # user's personal API keys and OAuth calls on the project they were already using.
        locked_user.current_organization_id = previous_organization_id
        locked_user.current_team_id = previous_team_id
        locked_user.save(update_fields=["current_organization", "current_team"])
        TeamProvisioningConfig.objects.create(team=team, application=partner)
        OrganizationProvisioning.objects.create(
            organization=organization,
            partner=OrganizationProvisioning.Partner.PROVISIONING_API,
            application=partner,
        )
    return team, True


def apply_provisioned_onboarding_flags(user: User, team: Team) -> None:
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
    org_name = partner_organization_name(partner, email, configuration.get("organization_name"))

    if signup_refused(email, call_site="agentic_provisioning"):
        capture_provisioning_event("account_request", "access_blocked", partner=partner, region=region)
        raise ProvisioningError(SECURITY_REFUSAL_CODE, SIGNUP_BLOCKED_DETAIL, request_id=request_id, status=403)

    try:
        with transaction.atomic():
            organization, team, user = User.objects.bootstrap(
                organization_name=org_name,
                email=email,
                password=None,
                first_name=first_name,
                is_email_verified=False,
            )
            TeamProvisioningConfig.objects.get_or_create(team=team, defaults={"application": partner})
            OrganizationProvisioning.objects.create(
                organization=organization,
                partner=OrganizationProvisioning.Partner.PROVISIONING_API,
                application=partner,
            )
    except IntegrityError:
        existing = EmailLookupHandler.get_user_by_email(email, is_active=None)
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

    try:
        reset_token = password_reset_token_generator.make_token(user)
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

    return {"id": request_id, "type": "oauth", "oauth": {"code": code}}


def resolve_pending_partner(partner_id: str) -> OAuthApplication | None:
    """Look up the partner referenced by a pending consent state; None when gone."""
    if not partner_id:
        return None
    try:
        return OAuthApplication.objects.get(id=partner_id)
    except OAuthApplication.DoesNotExist:
        return None
