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

        return self.team_effective_membership_level_for_parent_membership(self._organization_membership)

    def team_effective_membership_level_for_parent_membership(
        self, organization_membership: Optional["OrganizationMembership"]
    ) -> Optional["OrganizationMembership.Level"]:
        if organization_membership is None:
            return None

        if (
            not self.organization.is_feature_available(AvailableFeature.PROJECT_BASED_PERMISSIONING)
            or not self.team.access_control
        ):
            return organization_membership.level

        try:
            explicit_membership = organization_membership.explicit_team_memberships.all()[0]
            return explicit_membership.effective_level
        # Thrown if ee model is inaccessible or no explicit membership set
        except (AttributeError, IndexError):
            # Only organizations admins and above get implicit project membership
            if organization_membership.level < OrganizationMembership.Level.ADMIN:
                return None
            return organization_membership.level

    @cached_property
    def _organization_membership(self) -> Optional[OrganizationMembership]:
        return OrganizationMembership.objects.filter(organization=self.organization, user=self.user).first()
