from functools import cached_property
from typing import Dict, Optional

from posthog.constants import AvailableFeature
from posthog.models import Dashboard, Organization, OrganizationMembership, Team, User


class UserPermissions:
    def __init__(self, user: User, team: Team, organization: Organization):
        self.user_instance = user
        self.team_instance = team
        self.organization_instance = organization

        self._dashboard_permissions: Dict[int, UserDashboardPermissions] = {}

    @cached_property
    def team(self) -> "UserTeamPermissions":
        return UserTeamPermissions(self)

    def dashboard(self, dashboard: Dashboard) -> "UserDashboardPermissions":
        if dashboard.pk not in self._dashboard_permissions:
            self._dashboard_permissions[dashboard.pk] = UserDashboardPermissions(self, dashboard)
        return self._dashboard_permissions[dashboard.pk]

    @cached_property
    def organization_membership(self) -> Optional[OrganizationMembership]:
        return OrganizationMembership.objects.filter(
            organization=self.organization_instance, user=self.user_instance
        ).first()


class UserTeamPermissions:
    def __init__(self, user_permissions: "UserPermissions"):
        self.p = user_permissions

    @cached_property
    def effective_membership_level(self) -> Optional["OrganizationMembership.Level"]:
        """Return an effective membership level.
        None returned if the user has no explicit membership and organization access is too low for implicit membership.
        """

        return self.effective_membership_level_for_parent_membership(self.p.organization_membership)

    def effective_membership_level_for_parent_membership(
        self, organization_membership: Optional["OrganizationMembership"]
    ) -> Optional["OrganizationMembership.Level"]:
        if organization_membership is None:
            return None

        if (
            not self.p.organization_instance.is_feature_available(AvailableFeature.PROJECT_BASED_PERMISSIONING)
            or not self.p.team_instance.access_control
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


class UserDashboardPermissions:
    def __init__(self, user_permissions: "UserPermissions", dashboard: Dashboard):
        self.p = user_permissions
        self.dashboard = dashboard

    @cached_property
    def restriction_level(self) -> Dashboard.RestrictionLevel:
        return self.dashboard.effective_restriction_level

    @cached_property
    def can_restrict(self) -> bool:
        return self.dashboard.can_user_restrict(self.p.user_instance.pk)

    @cached_property
    def effective_privilege_level(self) -> Dashboard.PrivilegeLevel:
        return self.dashboard.get_effective_privilege_level(self.p.user_instance.pk)

    @cached_property
    def can_edit(self) -> bool:
        return self.dashboard.can_user_edit(self.p.user_instance.pk)
