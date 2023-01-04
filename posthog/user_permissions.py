from functools import cached_property
from typing import Optional

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User


class UserPermissions:
    def __init__(self, user: User, team: Team, organization: Organization):
        self.user = user
        self.team = team
        self.organization = organization

    @cached_property
    def team_effective_membership_level(self) -> Optional["OrganizationMembership.Level"]:
        """Return an effective membership level.
        None returned if the user has no explicit membership and organization access is too low for implicit membership.
        """
        from posthog.models.organization import OrganizationMembership

        try:
            requesting_parent_membership: OrganizationMembership = OrganizationMembership.objects.select_related(
                "organization"
            ).get(organization_id=self.organization.pk, user_id=self.user.pk)
        except OrganizationMembership.DoesNotExist:
            return None
        return self.get_effective_membership_level_for_parent_membership(requesting_parent_membership)

    def get_effective_membership_level_for_parent_membership(
        self, requesting_parent_membership: "OrganizationMembership"
    ) -> Optional["OrganizationMembership.Level"]:
        if (
            not requesting_parent_membership.organization.is_feature_available(
                AvailableFeature.PROJECT_BASED_PERMISSIONING
            )
            or not self.team.access_control
        ):
            return requesting_parent_membership.level
        from posthog.models.organization import OrganizationMembership

        try:
            from ee.models import ExplicitTeamMembership
        except ImportError:
            # Only organizations admins and above get implicit project membership
            if requesting_parent_membership.level < OrganizationMembership.Level.ADMIN:
                return None
            return requesting_parent_membership.level
        else:
            try:
                return (
                    requesting_parent_membership.explicit_team_memberships.only("parent_membership", "level")
                    .get(team=self.team)
                    .effective_level
                )
            except ExplicitTeamMembership.DoesNotExist:
                # Only organizations admins and above get implicit project membership
                if requesting_parent_membership.level < OrganizationMembership.Level.ADMIN:
                    return None
                return requesting_parent_membership.level
