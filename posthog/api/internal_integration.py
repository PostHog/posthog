import json
from typing import Any

from django.utils import timezone

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIAuthentication
from posthog.models.integration import Integration, dot_get
from posthog.models.oauth import OAuthAccessToken, OAuthRefreshToken
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.redis import get_client
from posthog.temporal.oauth import create_oauth_access_and_refresh_tokens_for_user, get_posthog_code_oauth_application

logger = structlog.get_logger(__name__)


VALID_INTEGRATION_KINDS: set[str] = {value for value, _ in Integration.IntegrationKind.choices}
VALID_USER_INTEGRATION_KINDS: set[str] = {value for value, _ in UserIntegration.IntegrationKind.choices}
VALID_KINDS: set[str] = VALID_INTEGRATION_KINDS | VALID_USER_INTEGRATION_KINDS

# Scopes minted for the bearer token returned alongside a lookup. Just enough
# for the hognipotent relay to create and stream tasks; nothing else.
_TASK_TOKEN_SCOPES = ["task:read", "task:write"]

# Cache the minted credential for at most 3 hours. The underlying OAuth access
# token has its own 6-hour DB-level expiry — keeping the cache strictly shorter
# ensures the caller never receives a token within ~3 hours of expiring.
_TOKEN_CACHE_TTL_SECONDS = 3 * 60 * 60
_TOKEN_CACHE_PREFIX = "posthog:internal_integration_lookup"


def _cache_key(scope_id: str, kind: str, integration_id: str) -> str:
    # Compose scope_id with (kind, integration_id) so a caller cannot accidentally
    # cross integrations by reusing a scope_id — each lookup gets its own bucket.
    return f"{_TOKEN_CACHE_PREFIX}:{scope_id}:{kind}:{integration_id}"


def _load_cached_tokens(cache_key: str) -> tuple[str, str, int] | None:
    """Refetch the OAuth (access, refresh) pair pointed at by the cached IDs.

    Returns None on cache miss, on missing rows, or when the cached pair is no
    longer usable (access token expired, refresh token revoked) — in any of
    those cases the caller should mint a fresh pair."""
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
    refresh_id = payload.get("refresh_token_id")
    if not access_id or not refresh_id:
        return None
    try:
        access = OAuthAccessToken.objects.get(pk=access_id)
        refresh = OAuthRefreshToken.objects.get(pk=refresh_id)
    except (OAuthAccessToken.DoesNotExist, OAuthRefreshToken.DoesNotExist):
        return None
    if access.is_expired() or refresh.revoked is not None:
        return None
    remaining = int((access.expires - timezone.now()).total_seconds())
    if remaining <= 0:
        return None
    return access.token, refresh.token, remaining


def _store_cached_token_ids(cache_key: str, access: OAuthAccessToken, refresh: OAuthRefreshToken) -> None:
    payload = {"access_token_id": str(access.pk), "refresh_token_id": str(refresh.pk)}
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
    membership level at-or-above admin, deterministic by user id."""
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


def _mint_task_tokens(user: User, team_id: int, cache_key: str) -> tuple[str, str, int] | None:
    cached = _load_cached_tokens(cache_key)
    if cached is not None:
        return cached
    try:
        access, refresh, expires_in = create_oauth_access_and_refresh_tokens_for_user(
            user,
            team_id,
            app=get_posthog_code_oauth_application(),
            scopes=_TASK_TOKEN_SCOPES,
            include_internal_scopes=False,
        )
    except Exception:
        logger.exception("internal_integration_lookup.mint_task_token_failed", user_id=user.id, team_id=team_id)
        return None
    _store_cached_token_ids(cache_key, access, refresh)
    return access.token, refresh.token, expires_in


def _token_fields(tokens: tuple[str, str, int] | None) -> dict[str, Any]:
    if tokens is None:
        return {"access_token": None, "refresh_token": None, "expires_in": None}
    access_token, refresh_token, expires_in = tokens
    return {"access_token": access_token, "refresh_token": refresh_token, "expires_in": expires_in}


class InternalIntegrationViewSet(viewsets.ViewSet):
    """Service-to-service lookups across the global Integration table.

    Authenticated with `X-Internal-Api-Secret` and not exposed to external
    ingress. Used by sibling services (e.g. the chat SDK relay) to discover
    which PostHog team owns a given third-party identifier without knowing
    the team in advance. Searches both team-level `Integration` rows and
    personal `UserIntegration` rows, preferring team matches.

    The caller passes a `scope_id` (their own session/conversation
    identifier); the IDs of the minted OAuth access + refresh token pair are
    cached in Redis under that scope for up to 3 hours, so repeated lookups
    within the same scope refetch the same DB rows rather than issuing fresh
    tokens on every request. The refresh token lets the caller renew via the
    regular /oauth/token grant flow without re-running this endpoint.
    """

    authentication_classes = [InternalAPIAuthentication]
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["internal"],
        summary="Look up the team/user that owns an integration",
        description=(
            "Resolve an external integration (e.g. a GitHub installation id, a verified phone number) "
            "to the PostHog team that owns it, and mint a short-lived OAuth access + refresh token pair "
            "for that team. Cached per scope_id for up to 3 hours."
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
            200: OpenApiResponse(description="Resolved team + minted OAuth tokens."),
            400: OpenApiResponse(description="Missing or invalid request fields."),
            404: OpenApiResponse(description="No matching integration."),
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

        cache_key = _cache_key(scope_id, kind, integration_id)

        team_match = (
            Integration.objects.filter(kind=kind, integration_id=integration_id)
            .select_related("team", "team__organization", "created_by")
            .order_by("id")
            .first()
        )
        if team_match is not None:
            organization_id = str(team_match.team.organization_id)
            token_user = team_match.created_by if team_match.created_by and team_match.created_by.is_active else None
            if token_user is None:
                token_user = _pick_org_admin(organization_id)
            tokens = _mint_task_tokens(token_user, team_match.team_id, cache_key) if token_user else None
            payload = {
                "source": "team",
                "team_id": team_match.team_id,
                "organization_id": organization_id,
                "integration_pk": str(team_match.id),
                "display_name": team_match.display_name,
                **_token_fields(tokens),
            }
            return Response(payload)

        user_match = (
            UserIntegration.objects.filter(kind=kind, integration_id=integration_id)
            .select_related("user", "user__current_team", "user__current_organization")
            .order_by("-created_at")
            .first()
        )
        if user_match is not None:
            user = user_match.user
            if user.current_team_id is None or user.current_organization_id is None:
                return Response({"error": "User has no current team"}, status=404)
            tokens = _mint_task_tokens(user, user.current_team_id, cache_key)
            payload = {
                "source": "user",
                "team_id": user.current_team_id,
                "organization_id": str(user.current_organization_id),
                "integration_pk": str(user_match.id),
                "display_name": _user_integration_display_name(user_match),
                "user_id": user.id,
                **_token_fields(tokens),
            }
            return Response(payload)

        return Response({"error": "Integration not found"}, status=404)
