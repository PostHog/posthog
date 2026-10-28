"""Access rules for referencing another project's insight from a cross-project dashboard."""

from typing import cast
from uuid import UUID

from rest_framework import serializers

from posthog.models import Organization, Team, User
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.user_access_control import UserAccessControl, visible_teams_for_user
from products.product_analytics.backend.facade.api import user_can_view_insight

NOT_AVAILABLE = "That insight is not available to you."


def visible_project_ids(user: User, organization_id: UUID | str) -> list[int]:
    """Projects in the organization the user may open, by both access-control systems, as the project list applies them."""
    organization = Organization.objects.get(id=organization_id)
    teams = visible_teams_for_user(
        organization,
        UserAccessControl(user=user, organization_id=str(organization_id)),
        UserPermissions(user=user),
    )
    return list(teams.values_list("id", flat=True))


def assert_can_reference_insight(user: User, organization_id: UUID | str, project_id: int, insight_id: int) -> None:
    """Allow a tile to reference an insight only when the user can already view it.

    This is a usability rule, not the security boundary. Every reader fetches each tile from
    that project's own insight endpoint, which enforces their own access independently.
    """
    # A dashboard references only its own organization's projects. A credential scoped to that
    # organization then cannot use a tile to probe a project in another one.
    team = Team.objects.filter(pk=project_id, organization_id=organization_id).first()
    if team is None:
        raise serializers.ValidationError({"project_id": NOT_AVAILABLE})

    # The project endpoints let an explicit member denial win over an allow for everyone, and
    # the legacy access resolution below does not, so both have to pass.
    if UserPermissions(user=user).team(team).effective_membership_level is None:
        raise serializers.ValidationError({"project_id": NOT_AVAILABLE})

    user_access_control = UserAccessControl(user=cast(User, user), team=team)

    # Resource and object rules fall back to a permissive default, so on their own they grant
    # access in a project the user was explicitly denied. Project access is a separate check.
    if not user_access_control.has_project_access:
        raise serializers.ValidationError({"project_id": NOT_AVAILABLE})

    if not user_can_view_insight(team=team, user=user, insight_id=insight_id):
        raise serializers.ValidationError({"insight_id": NOT_AVAILABLE})
