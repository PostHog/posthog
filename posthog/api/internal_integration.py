from typing import Any

import structlog
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIAuthentication
from posthog.models.integration import Integration, dot_get
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.temporal.oauth import create_oauth_access_token_for_user

logger = structlog.get_logger(__name__)


VALID_KINDS: set[str] = {value for value, _ in Integration.IntegrationKind.choices}


def _user_integration_display_name(integration: UserIntegration) -> str:
    if integration.kind == UserIntegration.IntegrationKind.GITHUB:
        return dot_get(integration.config, "account.name", integration.integration_id)
    return integration.integration_id or f"ID: {integration.id}"


# Scopes minted for the bearer token returned alongside a lookup. Just enough
# for the hognipotent relay to create and stream tasks; nothing else.
_TASK_TOKEN_SCOPES = ["task:read", "task:write"]


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


def _mint_task_token(user: User, team_id: int) -> str | None:
    try:
        return create_oauth_access_token_for_user(
            user,
            team_id,
            scopes=_TASK_TOKEN_SCOPES,
            include_internal_scopes=False,
        )
    except Exception:
        logger.exception("internal_integration_lookup.mint_task_token_failed", user_id=user.id, team_id=team_id)
        return None


class InternalIntegrationViewSet(viewsets.ViewSet):
    """Service-to-service lookups across the global Integration table.

    Authenticated with `X-Internal-Api-Secret` and not exposed to external
    ingress. Used by sibling services (e.g. the chat SDK relay) to discover
    which PostHog team owns a given third-party identifier without knowing
    the team in advance. Searches both team-level `Integration` rows and
    personal `UserIntegration` rows, preferring team matches.
    """

    authentication_classes = [InternalAPIAuthentication]
    permission_classes = [AllowAny]

    def lookup(self, request: Request, **kwargs: Any) -> Response:
        kind = request.data.get("kind")
        integration_id = request.data.get("integration_id")

        if not isinstance(kind, str) or kind not in VALID_KINDS:
            return Response({"error": "Invalid or unsupported kind"}, status=400)
        if not isinstance(integration_id, str) or not integration_id:
            return Response({"error": "integration_id is required"}, status=400)

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
            personal_api_key = _mint_task_token(token_user, team_match.team_id) if token_user else None
            return Response(
                {
                    "source": "team",
                    "team_id": team_match.team_id,
                    "organization_id": organization_id,
                    "integration_pk": str(team_match.id),
                    "display_name": team_match.display_name,
                    "personal_api_key": personal_api_key,
                }
            )

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
            personal_api_key = _mint_task_token(user, user.current_team_id)
            return Response(
                {
                    "source": "user",
                    "team_id": user.current_team_id,
                    "organization_id": str(user.current_organization_id),
                    "integration_pk": str(user_match.id),
                    "display_name": _user_integration_display_name(user_match),
                    "user_id": user.id,
                    "personal_api_key": personal_api_key,
                }
            )

        return Response({"error": "Integration not found"}, status=404)
