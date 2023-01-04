from functools import cached_property
from typing import Dict, Optional, cast

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
        return (
            self.dashboard.restriction_level
            if self.p.organization_instance.is_feature_available(AvailableFeature.DASHBOARD_PERMISSIONING)
            else Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )

    @cached_property
    def can_restrict(self) -> bool:
        # Sync conditions with frontend hasInherentRestrictionsRights
        from posthog.models.organization import OrganizationMembership

        # The owner (aka creator) has full permissions
        if self.p.user_instance.pk == self.dashboard.created_by_id:
            return True
        effective_project_membership_level = self.p.team.effective_membership_level
        return (
            effective_project_membership_level is not None
            and effective_project_membership_level >= OrganizationMembership.Level.ADMIN
        )

    @cached_property
    def effective_privilege_level(self) -> Dashboard.PrivilegeLevel:
        if (
            # Checks can be skipped if the dashboard in on the lowest restriction level
            self.dashboard.effective_restriction_level == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
            # Users with restriction rights can do anything
            or self.can_restrict
        ):
            # Returning the highest access level if no checks needed
            return Dashboard.PrivilegeLevel.CAN_EDIT

        try:
            from ee.models import DashboardPrivilege
        except ImportError:
            return Dashboard.PrivilegeLevel.CAN_VIEW
        else:
            try:
                return cast(
                    Dashboard.PrivilegeLevel,
                    self.dashboard.privileges.values_list("level", flat=True).get(user_id=self.p.user_instance.pk),
                )
            except DashboardPrivilege.DoesNotExist:
                # Returning the lowest access level if there's no explicit privilege for this user
                return Dashboard.PrivilegeLevel.CAN_VIEW

    @cached_property
    def can_edit(self) -> bool:
        if self.dashboard.effective_restriction_level < Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT:
            return True
        return self.effective_privilege_level >= Dashboard.PrivilegeLevel.CAN_EDIT
