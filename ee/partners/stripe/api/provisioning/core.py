"""Domain logic for the Stripe provisioning namespace.

The Stripe orchestrator is a fixed, partner-less identity: auth codes are
minted with an empty ``partner_id`` and token exchange binds to the Stripe
Projects OAuth app resolved from ``settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID``.
"""

from __future__ import annotations

import secrets
import unicodedata
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

import structlog

from posthog.api.authentication import password_reset_token_generator
from posthog.event_usage import report_user_signed_up
from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, mask_key_value
from posthog.rbac.user_access_control import UserAccessControl
from posthog.tasks.email import send_provisioning_welcome

from ee.partners.stripe.api.provisioning import AUTH_CODE_CACHE_PREFIX
from ee.partners.stripe.api.provisioning.analytics import capture_provisioning_event
from ee.partners.stripe.api.provisioning.constants import (
    ANALYTICS_SERVICE_ID,
    AUTH_CODE_TTL_SECONDS,
    DEEP_LINK_DISALLOWED_PATH_CHARS,
    DEEP_LINK_MAX_PATH_LENGTH,
    PROVISIONED_PAT_LABEL_MAX_LENGTH,
    PROVISIONED_PAT_LABEL_PREFIX_MAX_LENGTH,
    STRIPE_CONTRACTED_SCOPES,
)
from ee.partners.stripe.api.provisioning.exceptions import SpecError

logger = structlog.get_logger(__name__)

# Label used in the welcome email and default organization name.
PARTNER_LABEL = "Stripe"


# ---------------------------------------------------------------------------
# Stripe Projects OAuth app
# ---------------------------------------------------------------------------


class StripeOAuthAppMissingError(Exception):
    """The configured Stripe Projects OAuth app could not be resolved.

    Raised instead of fabricating an app on demand: a missing app is an
    operational misconfiguration, not something to paper over with a freshly
    created application.
    """


def get_stripe_oauth_app() -> OAuthApplication:
    client_id = settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID
    if not client_id:
        error = StripeOAuthAppMissingError("STRIPE_POSTHOG_OAUTH_CLIENT_ID is not configured")
        capture_exception(error)
        raise error

    try:
        app = OAuthApplication.objects.get(client_id=client_id)
    except OAuthApplication.DoesNotExist as exc:
        error = StripeOAuthAppMissingError("Stripe Projects OAuth app not found for configured client_id")
        # Chain the DoesNotExist so the captured event keeps its traceback; the new
        # error was never raised, so it carries no traceback of its own.
        error.__cause__ = exc
        capture_exception(error, additional_properties={"client_id": client_id})
        raise error from None

    return app


def is_stripe_oauth_app(app: OAuthApplication) -> bool:
    """True when ``app`` is the configured Stripe Projects OAuth app.

    Fails closed when ``STRIPE_POSTHOG_OAUTH_CLIENT_ID`` is unset: with no
    configured Stripe identity, no caller can be the Stripe orchestrator.
    """
    client_id = settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID
    return bool(client_id) and app.client_id == client_id


def get_oauth_app_for_code(code_data: dict) -> OAuthApplication:
    """Resolve the OAuthApplication for a token exchange.

    Codes minted in this namespace always carry an empty ``partner_id`` and
    resolve to the Stripe Projects app; codes minted by the interactive consent
    flow may carry a partner id and keep their original app binding. The token
    view rejects any resolved app that is not the Stripe Projects app - this
    namespace serves no other partner.
    """
    partner_id = code_data.get("partner_id", "")
    if partner_id:
        try:
            return OAuthApplication.objects.get(id=partner_id)
        except OAuthApplication.DoesNotExist:
            pass

    return get_stripe_oauth_app()


def lock_application(application_id: Any) -> OAuthApplication | None:
    """Row-lock the OAuthApplication so direct-mint serializes with revoke_application_sessions.

    The revoke updates this row first and holds the lock for its whole transaction before
    sweeping tokens, so a mint that takes the same lock is forced into one of two safe orders:
    it holds the lock and its new tokens land before the revoke's sweep (which then catches
    them), or the revoke committed first and the caller reads the now-visible
    `sessions_revoked_at` and rejects. Must be called inside `transaction.atomic()`.
    """
    return OAuthApplication.objects.select_for_update().filter(pk=application_id).first()


# ---------------------------------------------------------------------------
# Account requests
# ---------------------------------------------------------------------------


def mint_auth_code(
    *,
    user_id: int,
    org_id: str,
    team_id: int,
    partner_account_id: str,
    scopes: list[str],
    region: str,
    code_challenge: str,
    code_challenge_method: str,
) -> str:
    """Mint a single-use auth code in the shared cache.

    The value shape is a cross-surface contract: any provisioning token
    endpoint must be able to redeem it. ``partner_id`` is always empty -
    Stripe is a fixed, partner-less identity.
    """
    code = secrets.token_urlsafe(32)
    cache.set(
        f"{AUTH_CODE_CACHE_PREFIX}{code}",
        {
            "issued_at": timezone.now().isoformat(),
            "user_id": user_id,
            "org_id": org_id,
            "team_id": team_id,
            "stripe_account_id": partner_account_id,
            "partner_id": "",
            "scopes": scopes,
            "region": region,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        },
        timeout=AUTH_CODE_TTL_SECONDS,
    )
    return code


def resolve_team_for_existing_user(user: User, requested_team_id: int | None = None) -> Team | None:
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

    # TODO: latent bug - memberships is unordered, so which organization hosts
    # the new project is arbitrary for multi-org users.
    organization = memberships[0].organization
    return Team.objects.create_with_data(initiating_user=user, organization=organization)


def handle_existing_user(
    request_id: str,
    user: User,
    scopes: list[str],
    partner_account_id: str,
    region: str,
    requested_team_id: int | None,
    code_challenge: str,
    code_challenge_method: str,
) -> dict[str, Any]:
    """Silently mint an auth code for an existing account."""
    team = resolve_team_for_existing_user(user, requested_team_id)
    if team is None:
        capture_provisioning_event("account_request", "error", error_code="team_resolution_failed")
        raise SpecError("team_resolution_failed", "Could not resolve a project for this user", request_id=request_id)

    code = mint_auth_code(
        user_id=user.id,
        org_id=str(team.organization_id),
        team_id=team.id,
        partner_account_id=partner_account_id,
        scopes=scopes,
        region=region,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )

    capture_provisioning_event("account_request", "existing_user", region=region, team_id=team.id)

    return {"id": request_id, "type": "oauth", "oauth": {"code": code}}


def handle_new_user(
    request_id: str,
    data: dict[str, Any],
    email: str,
    scopes: list[str],
    partner_account_id: str,
    region: str,
    code_challenge: str,
    code_challenge_method: str,
) -> dict[str, Any]:
    """Bootstrap a fresh account and mint an auth code."""
    name = data.get("name", "")
    first_name = name.split(" ")[0] if name else ""

    configuration = data.get("configuration")
    if not isinstance(configuration, dict):
        configuration = {}

    # TODO: latent bug - organization_name is unvalidated; a non-string or
    # over-long value fails at the DB layer as an uncaught TypeError/DataError
    # (500) where the spec calls for a 400 invalid_request.
    org_name = configuration.get("organization_name") or f"{PARTNER_LABEL} ({email})"

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
                partner_account_id,
                region,
                None,
                code_challenge,
                code_challenge_method,
            )
        capture_provisioning_event("account_request", "creation_failed", region=region)
        raise SpecError("account_creation_failed", "Failed to create account", request_id=request_id, status=500)

    capture_provisioning_event("account_request", "new_user", region=region, team_id=team.id)

    # Emit the standard signup event so provisioned accounts flow into the shared
    # signup / activation / billing analyses, segmentable by client.
    report_user_signed_up(
        user,
        is_instance_first_user=False,
        is_organization_first_user=True,
        backend_processor="AgenticProvisioning",
        social_provider="",
        user_analytics_metadata=user.get_analytics_metadata(),
        org_analytics_metadata=organization.get_analytics_metadata(),
    )

    try:
        reset_token = password_reset_token_generator.make_token(user)
        send_provisioning_welcome.delay(user.id, reset_token, PARTNER_LABEL)
    except Exception:
        capture_exception(additional_properties={"user_id": user.id, "step": "provisioning_welcome_email"})

    code = mint_auth_code(
        user_id=user.id,
        org_id=str(organization.id),
        team_id=team.id,
        partner_account_id=partner_account_id,
        scopes=scopes,
        region=region,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )

    return {"id": request_id, "type": "oauth", "oauth": {"code": code}}


# ---------------------------------------------------------------------------
# Team scoping
# ---------------------------------------------------------------------------


def user_can_access_team(user: User, team: Team) -> bool:
    """Verify the user has at least member-level access to the team.

    Org membership alone does not prove access for advanced-permissions
    orgs that restrict individual teams. Without this check the resolve flow
    could grant scoped access to a private team as long as the user had any
    team in the same org.
    """
    return UserAccessControl(user=user, team=team).check_access_level_for_object(team, required_level="member")


def compute_partner_scoped_teams(
    application: OAuthApplication | None,
    user: User,
    base_team_id: int,
) -> list[int]:
    """Compute the durable scope for an OAuth token at issuance/refresh.

    Returns the set of every team where ``TeamProvisioningConfig.application ==
    application`` (i.e. this app provisioned the team for this user, attributed
    at create time) AND the team lives in the same organization as ``base_team_id``
    AND the user still has team-level access. The organization filter pins the
    token to the authorization context: an app with OAuth grants in multiple orgs
    for the same user must not be able to reach an org-B team via an org-A token
    just because the user happens to be a member of both.

    Returns ``[]`` when ``application`` is None (legacy refresh tokens with no
    app binding). An unattributed token cannot be safely scoped, so it gets no
    teams and the holder must re-authorize. Falling through would let
    ``filter(application=None)`` match every TeamProvisioningConfig row with a
    NULL application across every partner.

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
    if not user_can_access_team(user, base_team):
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
        if user_can_access_team(user, team):
            granted.add(team.id)

    # sorted() only for deterministic test assertions and log diffs; scope order is not a correctness requirement
    return sorted(granted)


def add_team_to_token_scopes(access_token: OAuthAccessToken, team_id: int) -> None:
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


def remove_team_from_token_scopes(access_token: OAuthAccessToken, team_id: int) -> None:
    """Strip ``team_id`` from every access/refresh token for this app+user combo.

    Removing a resource has to revoke access for any *other* live token the same
    partner installation might be holding for the same user (e.g. a separate
    bearer issued via a prior OAuth grant that still has the team in scope).
    Touching only the calling ``access_token`` would let the partner continue
    operating on the team via a sibling token after `remove` returned, since
    operational endpoints accept any team currently in ``scoped_teams``.

    Atomic so a refresh token can never be left with the removed team still in
    scope while the access token has it stripped - otherwise the orchestrator
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


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class ProjectIdCollisionError(Exception):
    """Raised when a project_id is already in use by a team outside the caller's orgs."""

    def __init__(self, project_id: str) -> None:
        super().__init__(project_id)
        self.project_id = project_id


def _ensure_team_in_token_scopes(
    access_token: OAuthAccessToken, scoped_teams: list[int], team: Team
) -> tuple[Team, list[int]]:
    if team.id in scoped_teams:
        return team, scoped_teams
    add_team_to_token_scopes(access_token, team.id)
    return team, [*scoped_teams, team.id]


def resolve_or_create_project_team(
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
        if not user_can_access_team(user, existing.team):
            return None, scoped_teams
        return _ensure_team_in_token_scopes(access_token, scoped_teams, existing.team)

    base_team = Team.objects.get(id=scoped_teams[0])
    if not user_can_access_team(user, base_team):
        return None, scoped_teams

    # TODO: latent bug - project_name is unvalidated; a non-string or over-long
    # value fails at the DB layer (500) where the spec calls for a 400
    # invalid_request.
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
            if not user_can_access_team(user, race_winner.team):
                return None, scoped_teams
            return _ensure_team_in_token_scopes(access_token, scoped_teams, race_winner.team)
        raise ProjectIdCollisionError(project_id)

    return _ensure_team_in_token_scopes(access_token, scoped_teams, new_team)


def get_provisioning_service_id(team: Team) -> str:
    try:
        config = TeamProvisioningConfig.objects.get(team=team)
        return config.service_id
    except TeamProvisioningConfig.DoesNotExist:
        return ANALYTICS_SERVICE_ID


def set_provisioning_service_id(team: Team, service_id: str) -> None:
    TeamProvisioningConfig.objects.update_or_create(
        team=team,
        defaults={"service_id": service_id},
    )


# ---------------------------------------------------------------------------
# Provisioned personal API keys
# ---------------------------------------------------------------------------


def validate_label_prefix(raw: Any) -> str | None:
    """Validate the optional ``label_prefix`` request field.

    Returns ``None`` when the field is absent or empty (caller creates an
    unprefixed label). Raises :class:`SpecError` (``invalid_label_prefix``)
    when the field is present but malformed (wrong type, too long, or contains
    control or format characters that would render badly in the user's PAT
    list).
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise SpecError("invalid_label_prefix", "label_prefix must be a string")

    stripped = raw.strip()
    if not stripped:
        return None

    if len(stripped) > PROVISIONED_PAT_LABEL_PREFIX_MAX_LENGTH:
        raise SpecError(
            "invalid_label_prefix",
            f"label_prefix must be {PROVISIONED_PAT_LABEL_PREFIX_MAX_LENGTH} characters or fewer",
        )

    # Reject Unicode control (Cc), format (Cf), and line/paragraph separators (Zl/Zp).
    # Cf is the important one - it includes bidi overrides (U+202A-U+202E) and
    # isolates (U+2066-U+2069), which a partner could use to re-order surrounding
    # text in the user's settings page (Trojan Source class). Cc covers C0 + DEL.
    if any(unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} for c in stripped):
        raise SpecError("invalid_label_prefix", "label_prefix must not contain control or format characters")

    return stripped


def maybe_create_provisioned_pat(
    user: User, team: Team, granted_scope: str | None, label_prefix: str | None = None
) -> str | None:
    """Create a Personal API Key for the provisioned user and return the raw value.

    The key carries the granted OAuth token's scopes (``granted_scope``) as-is;
    this namespace does not enforce a scope ceiling, so what the token was
    granted is exactly what the PAT gets. Falls back to the default Stripe scope
    set when the token carried none.

    scoped_teams is set to [team.id] so the PAT only grants access to the team
    being provisioned, matching the scoping of the OAuth token issued in the
    same flow. Without this, a provisioning call from an existing user would
    return a PAT that reaches across every team the user already belongs to.

    ``label_prefix`` should be pre-validated by ``validate_label_prefix``; pass
    ``None`` (or any falsy value) to label the key with just the team name.
    """
    pat_scopes = [s for s in (granted_scope or "").split() if s] or list(STRIPE_CONTRACTED_SCOPES)
    # TODO: latent bug - every call mints a new PAT without revoking earlier
    # ones, so rotate_credentials accumulates live keys instead of rotating
    # them. A correct fix needs a provenance marker on PersonalAPIKey (or the
    # provisioned key id recorded on TeamProvisioningConfig) so revocation can
    # target only provisioned keys - scope alone is ambiguous with keys a user
    # created via /api/personal_api_keys/ carrying the same team/org scope.
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


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def get_available_teams_for_user(user: User) -> list[dict[str, Any]]:
    """Return the user's non-demo teams for inclusion in the token exchange response.

    Applies the same member-level access check as the scoping paths so names of
    restricted teams in advanced-permissions orgs are not listed.
    """
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
        if user_can_access_team(user, team)
    ]


def region_to_host(region: str) -> str:
    region_lower = region.lower()
    if region_lower == "eu":
        return "https://eu.posthog.com"
    elif region_lower in ("us", "dev"):
        return "https://us.posthog.com"
    return settings.SITE_URL


def is_safe_deep_link_path(path: object) -> bool:
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
