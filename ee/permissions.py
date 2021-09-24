from typing import Optional, cast

from rest_framework.permissions import SAFE_METHODS, BasePermission

from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User


def get_ephemeral_requesting_team_membership(team: Team, user: User) -> Optional[ExplicitTeamMembership]:
    """Return an ExplicitTeamMembership instance only for permission checking.
    None returned if the user has no explicit membership and organization access is too low for implicit membership."""
    try:
        requesting_parent_membership: OrganizationMembership = OrganizationMembership.objects.select_related(
            "organization"
        ).get(organization_id=team.organization_id, user=user)
    except OrganizationMembership.DoesNotExist:
        # If the user does not belong to the organization at all, they of course have no access
        return None
    if team.access_control and requesting_parent_membership.organization.is_feature_available(
        AvailableFeature.PROJECT_BASED_PERMISSIONING
    ):
        try:
            return ExplicitTeamMembership.objects.select_related(
                "team", "parent_membership", "parent_membership__user"
            ).get(team=team, parent_membership=requesting_parent_membership)
        except ExplicitTeamMembership.DoesNotExist:
            # Only organizations admins and above get implicit project membership
            if requesting_parent_membership.level < OrganizationMembership.Level.ADMIN:
                return None
    # If project-based permissioning is disabled or unavailable, or membership is implicit,
    # we instantiate an ephemeral membership just for validation
    return ExplicitTeamMembership(
        id="ephemeral",
        team=team,
        parent_membership=requesting_parent_membership,
        level=requesting_parent_membership.level,
    )


class TeamMemberAccessPermission(BasePermission):
    """Require effective project membership for any access at all."""

    message = "You don't have access to the project."

    def has_permission(self, request, view) -> bool:
        try:
            team = view.team
        except Team.DoesNotExist:
            return True  # This will be handled as a 404 in the viewset
        requesting_team_membership = get_ephemeral_requesting_team_membership(team, cast(User, request.user))
        return requesting_team_membership is not None and requesting_team_membership.effective_level is not None


class TeamMemberLightManagementPermission(BasePermission):
    """
    Require effective project membership for any access at all,
    and at least admin effective project access level for write/delete.
    """

    message = "You don't have sufficient permissions in the project."

    def has_permission(self, request, view) -> bool:
        try:
            if request.resolver_match.url_name == "team-detail":
                # /projects/ endpoint handling
                team = view.get_object()
            else:
                team = view.team
        except Team.DoesNotExist:
            return True  # This will be handled as a 404 in the viewset
        requesting_team_membership = get_ephemeral_requesting_team_membership(team, cast(User, request.user))
        if requesting_team_membership is None:
            return False
        minimum_level = (
            ExplicitTeamMembership.Level.MEMBER if request.method != "DELETE" else ExplicitTeamMembership.Level.ADMIN
        )
        return requesting_team_membership.effective_level >= minimum_level


class TeamMemberStrictManagementPermission(BasePermission):
    """
    Require effective project membership for any access at all,
    and at least admin effective project access level for write/delete.
    """

    message = "You don't have sufficient permissions in the project."

    def has_permission(self, request, view) -> bool:
        team = view.team
        requesting_team_membership = get_ephemeral_requesting_team_membership(team, cast(User, request.user))
        if requesting_team_membership is None:
            return False
        minimum_level = (
            ExplicitTeamMembership.Level.MEMBER
            if request.method in SAFE_METHODS
            else ExplicitTeamMembership.Level.ADMIN
        )
        return requesting_team_membership.effective_level >= minimum_level
