import json
from typing import Any

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIAuthentication
from posthog.models.integration import Integration, dot_get
from posthog.models.oauth import OAuthAccessToken
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.redis import get_client
from posthog.temporal.oauth import create_oauth_access_token_for_user, get_posthog_code_oauth_application
from posthog.user_permissions import UserPermissions

logger = structlog.get_logger(__name__)


VALID_INTEGRATION_KINDS: set[str] = {value for value, _ in Integration.IntegrationKind.choices}
VALID_USER_INTEGRATION_KINDS: set[str] = {value for value, _ in UserIntegration.IntegrationKind.choices}
VALID_KINDS: set[str] = VALID_INTEGRATION_KINDS | VALID_USER_INTEGRATION_KINDS

# Scopes minted for the bearer token returned alongside a lookup. Just enough
# for the hognipotent relay to create and stream tasks; nothing else.
_TASK_TOKEN_SCOPES = ["task:read", "task:write"]

# Cache the access token's DB id for up to 5 hours. The underlying OAuth access
# token has a 6-hour DB-level expiry, so a cached token handed back to the
# caller always has at least 1 hour of life left (6h - 5h) — short enough to
# keep tokens rotating, long enough that callers never need to plumb refresh
# logic. That's also why we no longer mint a refresh token: every response
# carries an access token with a comfortable runway.
_TOKEN_CACHE_TTL_SECONDS = 5 * 60 * 60
_TOKEN_CACHE_PREFIX = "posthog:internal_integration_lookup"


def _cache_key(scope_id: str, kind: str, integration_id: str, integration_pk: str) -> str:
    # Compose scope_id with (kind, integration_id, integration_pk) so a caller cannot
    # accidentally cross integrations by reusing a scope_id, and the cache is invalidated
    # automatically when ownership of an external identifier moves to a different row
    # (e.g. an SMS number being reassigned to another user creates a new UserIntegration
    # row with a new pk). Without the pk component, a stale cached token for a previous
    # owner could be returned for up to the cache TTL.
    return f"{_TOKEN_CACHE_PREFIX}:{scope_id}:{kind}:{integration_id}:{integration_pk}"


def _load_cached_token(cache_key: str) -> str | None:
    """Refetch the OAuth access token pointed at by the cached id.

    Returns None on cache miss, on a missing row, or when the cached token is
    no longer usable (expired) — in any of those cases the caller should mint
    a fresh one."""
    try:
        raw = get_client().get(cache_key)
    except Exception:
        logger.exception("internal_integration_lookup.cache_read_failed", cache_key=cache_key)
        return None
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("internal_integration_lookup.cache_payload_invalid", cache_key=cache_key)
        return None

    access_id = payload.get("access_token_id")
    if not access_id:
        return None
    try:
        access = OAuthAccessToken.objects.get(pk=access_id)
    except OAuthAccessToken.DoesNotExist:
        return None
    if access.is_expired():
        return None
    return access.token


def _store_cached_token_id(cache_key: str, access: OAuthAccessToken) -> None:
    payload = {"access_token_id": str(access.pk)}
    try:
        get_client().set(cache_key, json.dumps(payload), ex=_TOKEN_CACHE_TTL_SECONDS)
    except Exception:
        logger.exception("internal_integration_lookup.cache_write_failed", cache_key=cache_key)


def _user_integration_display_name(integration: UserIntegration) -> str:
    if integration.kind == UserIntegration.IntegrationKind.GITHUB:
        return dot_get(integration.config, "account.name", integration.integration_id)
    return integration.integration_id or f"ID: {integration.id}"


def _pick_org_admin(organization_id: str) -> User | None:
    """Pick a representative admin to mint a task token under for a team-level
    integration. Mirrors the strategy in ee/billing/billing_manager.py: lowest
    membership level at-or-above admin, deterministic by user id. Org admins
    always have effective access to every project in the org (see
    `UserTeamPermissions.effective_membership_level_for_parent_membership`),
    so no additional per-team access check is needed here."""
    membership = (
        OrganizationMembership.objects.filter(
            organization_id=organization_id,
            level__gte=OrganizationMembership.Level.ADMIN,
            user__is_active=True,
        )
        .select_related("user")
        .order_by("level", "user_id")
        .first()
    )
    return membership.user if membership else None


def _user_can_drive_team_tasks(user: User, team: Team) -> bool:
    """Whether the user is eligible to mint a task token scoped to this team.

    Requires the user to be active and to have effective project access to
    the team. Org membership alone is not enough: a private project (or a
    revoked RBAC role) can leave a user in the org with no access to the
    team the token would scope to, and that user must not retain the
    ability to drive task actions there through an integration."""
    if not user.is_active:
        return False
    return UserPermissions(user).team(team).effective_membership_level is not None


def _mint_task_token(user: User, team_id: int, cache_key: str) -> str | None:
    cached = _load_cached_token(cache_key)
    if cached is not None:
        return cached
    try:
        access = create_oauth_access_token_for_user(
            user,
            team_id,
            app=get_posthog_code_oauth_application(),
            scopes=_TASK_TOKEN_SCOPES,
            include_internal_scopes=False,
        )
    except Exception:
        logger.exception("internal_integration_lookup.mint_task_token_failed", user_id=user.id, team_id=team_id)
        return None
    _store_cached_token_id(cache_key, access)
    return access.token


class InternalIntegrationViewSet(viewsets.ViewSet):
    """Service-to-service lookups across the global Integration table.

    Authenticated with `X-Internal-Api-Secret` and not exposed to external
    ingress. Used by sibling services (e.g. the chat SDK relay) to discover
    which PostHog team owns a given third-party identifier without knowing
    the team in advance. Searches both team-level `Integration` rows and
    personal `UserIntegration` rows, preferring team matches.

    The caller passes a `scope_id` (their own session/conversation
    identifier); the id of the minted OAuth access token is cached in Redis
    under that scope for up to 5 hours, so repeated lookups within the same
    scope refetch the same DB row rather than issuing fresh tokens on every
    request. The 5h cache TTL against the access token's 6h DB-level expiry
    guarantees the caller is always handed a token with at least 1h of life
    left, so they don't need to implement refresh.
    """

    authentication_classes = [InternalAPIAuthentication]
    # InternalAPIAuthentication returns None when the X-Internal-Api-Secret
    # header is missing (DRF convention), so we rely on IsAuthenticated to
    # reject anonymous traffic. When the header is present but invalid the
    # auth class still raises and the request never reaches the permission
    # check.
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["internal"],
        summary="Look up the team/user that owns an integration",
        description=(
            "Resolve an external integration (e.g. a GitHub installation id, a verified phone number) "
            "to the PostHog team that owns it, and mint a short-lived OAuth access token for that team. "
            "Cached per scope_id for up to 5 hours; the returned token always has at least 1 hour of life "
            "left, so callers do not need to implement refresh."
        ),
        request={
            "application/json": {
                "type": "object",
                "required": ["kind", "integration_id", "scope_id"],
                "properties": {
                    "kind": {"type": "string", "description": "Integration kind (e.g. `github`, `sms`)."},
                    "integration_id": {"type": "string", "description": "External identifier on that kind."},
                    "scope_id": {
                        "type": "string",
                        "description": "Caller-chosen session identifier; tokens are cached per scope.",
                    },
                },
            }
        },
        responses={
            200: OpenApiResponse(description="Resolved team + minted OAuth access token."),
            400: OpenApiResponse(description="Missing or invalid request fields."),
            404: OpenApiResponse(description="No matching integration."),
            503: OpenApiResponse(
                description="Integration found but no OAuth token could be minted (no eligible admin, or token issuer error)."
            ),
        },
    )
    def lookup(self, request: Request, **kwargs: Any) -> Response:
        kind = request.data.get("kind")
        integration_id = request.data.get("integration_id")
        scope_id = request.data.get("scope_id")

        if not isinstance(kind, str) or kind not in VALID_KINDS:
            return Response({"error": "Invalid or unsupported kind"}, status=400)
        if not isinstance(integration_id, str) or not integration_id:
            return Response({"error": "integration_id is required"}, status=400)
        if not isinstance(scope_id, str) or not scope_id:
            return Response({"error": "scope_id is required"}, status=400)

        # `Integration` only enforces uniqueness of (kind, integration_id) per team, so the
        # same external workspace connected to two PostHog projects would otherwise resolve
        # to whichever row sorts first and mint a task token for the wrong project. Fetch
        # two rows and refuse to disambiguate when more than one team owns the identifier —
        # the caller has to pass a team-scoped lookup, or the integration has to be cleaned
        # up, before a token can be minted.
        team_matches = list(
            Integration.objects.filter(kind=kind, integration_id=integration_id)
            .select_related("team", "team__organization", "created_by")
            .order_by("id")[:2]
        )
        if len(team_matches) > 1:
            return Response(
                {"error": "Multiple teams own this integration; cannot disambiguate"},
                status=409,
            )
        team_match = team_matches[0] if team_matches else None
        if team_match is not None:
            organization_id = str(team_match.team.organization_id)
            cache_key = _cache_key(scope_id, kind, integration_id, str(team_match.id))
            # The original integration creator can only mint a task token if they
            # are still active, a member of the owning organization, and have
            # effective project access to the integration's team. Losing access
            # on a private project (or via revoked RBAC role) must revoke the
            # creator's ability to drive team tasks through the integration —
            # fall back to an org admin in that case.
            token_user = (
                team_match.created_by
                if team_match.created_by and _user_can_drive_team_tasks(team_match.created_by, team_match.team)
                else None
            )
            if token_user is None:
                token_user = _pick_org_admin(organization_id)
            access_token = _mint_task_token(token_user, team_match.team_id, cache_key) if token_user else None
            if access_token is None:
                return Response({"error": "Could not mint access token for integration"}, status=503)
            return Response(
                {
                    "source": "team",
                    "team_id": team_match.team_id,
                    "organization_id": organization_id,
                    "integration_pk": str(team_match.id),
                    "display_name": team_match.display_name,
                    "access_token": access_token,
                }
            )

        # Apply the same disambiguation rule to personal integrations — `UserIntegration`
        # does not globally enforce uniqueness either (it only does so for the SMS kind via
        # a partial unique constraint), so a duplicate external id across two users must
        # also refuse to mint a token.
        user_matches = list(
            UserIntegration.objects.filter(kind=kind, integration_id=integration_id)
            .select_related("user", "user__current_team", "user__current_organization")
            .order_by("-created_at")[:2]
        )
        if len(user_matches) > 1:
            return Response(
                {"error": "Multiple users own this integration; cannot disambiguate"},
                status=409,
            )
        user_match = user_matches[0] if user_matches else None
        if user_match is not None:
            user = user_match.user
            cache_key = _cache_key(scope_id, kind, integration_id, str(user_match.id))
            if user.current_team_id is None or user.current_organization_id is None or user.current_team is None:
                return Response({"error": "User has no current team"}, status=404)
            # Personal integrations must not keep granting a token to a user who
            # has been disabled, removed from the organization, or lost project
            # access to the team the token would scope to (e.g. a private
            # project the user can no longer see). Org membership alone is not
            # sufficient — RBAC can leave a member with zero access to a team.
            if not _user_can_drive_team_tasks(user, user.current_team):
                return Response({"error": "User cannot access the current team"}, status=404)
            access_token = _mint_task_token(user, user.current_team_id, cache_key)
            if access_token is None:
                return Response({"error": "Could not mint access token for integration"}, status=503)
            return Response(
                {
                    "source": "user",
                    "team_id": user.current_team_id,
                    "organization_id": str(user.current_organization_id),
                    "integration_pk": str(user_match.id),
                    "display_name": _user_integration_display_name(user_match),
                    "user_id": user.id,
                    "access_token": access_token,
                }
            )

        return Response({"error": "Integration not found"}, status=404)
