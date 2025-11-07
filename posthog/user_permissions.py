from functools import cached_property
from typing import Any, Optional, cast
from uuid import UUID

from posthog.constants import AvailableFeature
from posthog.models import Dashboard, DashboardTile, Insight, Organization, OrganizationMembership, Team, User


class UserPermissions:
    """
    Class responsible for figuring out user permissions in an efficient manner.

    Generally responsible for the following tasks:
    1. Calculating whether a user has access to the current team
    2. Calculating whether a user has access to other team(s)
    3. Calculating permissioning of a certain object (dashboard, insight) in the team

    Note that task 3 depends on task 1, so for efficiency sake the class _generally_
    expects the current team/organization to be passed to it and will use it to skip certain
    lookups.
    """

    def __init__(self, user: User, team: Optional[Team] = None):
        self.user = user
        self._current_team = team

        self._tiles: Optional[list[DashboardTile]] = None
        self._team_permissions: dict[int, UserTeamPermissions] = {}
        self._dashboard_permissions: dict[int, UserDashboardPermissions] = {}
        self._insight_permissions: dict[int, UserInsightPermissions] = {}

    @cached_property
    def current_team(self) -> "UserTeamPermissions":
        if self._current_team is None:
            raise ValueError("Cannot call .current_team without passing it to UserPermissions")

        return UserTeamPermissions(self, self._current_team)

    def team(self, team: Team) -> "UserTeamPermissions":
        if self._current_team and team.pk == self._current_team.pk:
            return self.current_team
        if team.pk not in self._team_permissions:
            self._team_permissions[team.pk] = UserTeamPermissions(self, team)
        return self._team_permissions[team.pk]

    def dashboard(self, dashboard: Dashboard) -> "UserDashboardPermissions":
        if self._current_team is None:
            raise ValueError("Cannot call .dashboard without passing current team to UserPermissions")

        if dashboard.pk not in self._dashboard_permissions:
            self._dashboard_permissions[dashboard.pk] = UserDashboardPermissions(self, dashboard)
        return self._dashboard_permissions[dashboard.pk]

    def insight(self, insight: Insight) -> "UserInsightPermissions":
        if self._current_team is None:
            raise ValueError("Cannot call .insight without passing current team to UsePermissions")

        if insight.pk not in self._insight_permissions:
            self._insight_permissions[insight.pk] = UserInsightPermissions(self, insight)
        return self._insight_permissions[insight.pk]

    @cached_property
    def teams_visible_for_user(self) -> list[Team]:
        candidate_teams = Team.objects.filter(organization_id__in=self.organizations.keys()).only(
            "pk", "organization_id"
        )
        return [team for team in candidate_teams if self.team(team).effective_membership_level is not None]

    @cached_property
    def team_ids_visible_for_user(self) -> list[int]:
        return [team.pk for team in self.teams_visible_for_user]

    @cached_property
    def project_ids_visible_for_user(self) -> list[int]:
        return list({team.project_id for team in self.teams_visible_for_user})

    # Cached properties/functions for efficient lookups in other classes

    @cached_property
    def current_organization(self) -> Optional[Organization]:
        if self._current_team is None:
            raise ValueError("Cannot call .current_organization without passing current team to UsePermissions")
        return self.get_organization(self._current_team.organization_id)

    def get_organization(self, organization_id: UUID) -> Optional[Organization]:
        return self.organizations.get(organization_id)

    @cached_property
    def organizations(self) -> dict[UUID, Organization]:
        return {member.organization_id: member.organization for member in self.organization_memberships.values()}

    @cached_property
    def organization_memberships(self) -> dict[UUID, OrganizationMembership]:
        memberships = OrganizationMembership.objects.filter(user=self.user).select_related("organization")
        return {membership.organization_id: membership for membership in memberships}

    @cached_property
    def dashboard_privileges(self) -> dict[int, Dashboard.PrivilegeLevel]:
        try:
            from ee.models import DashboardPrivilege

            rows = DashboardPrivilege.objects.filter(user=self.user).values_list("dashboard_id", "level")
            return {dashboard_id: cast(Dashboard.PrivilegeLevel, level) for dashboard_id, level in rows}
        except ImportError:
            return {}

    @cached_property
    def _prefetched_access_controls(self) -> dict[int, list[dict[str, Any]]]:
        """
        Prefetch all AccessControl entries for teams in user's organizations.
        Returns a dict mapping team_id to list of access control entries.
        """
        from ee.models.rbac.access_control import AccessControl

        organization_ids = list(self.organizations.keys())
        # Get all access controls for teams in these organizations
        access_controls = AccessControl.objects.filter(
            team__organization_id__in=organization_ids, resource="project"
        ).values("team_id", "resource_id", "organization_member_id", "role_id", "access_level")

        # Group by team_id
        result: dict[int, list[dict[str, Any]]] = {}
        for ac in access_controls:
            team_id = ac["team_id"]
            if team_id not in result:
                result[team_id] = []
            result[team_id].append(dict(ac))
        return result

    @cached_property
    def _prefetched_role_memberships(self) -> dict[UUID, list[UUID]]:
        """
        Prefetch all role memberships for the user.
        Returns a dict mapping organization_member_id to list of role_ids.
        """
        from ee.models.rbac.role import RoleMembership

        memberships = RoleMembership.objects.filter(user=self.user).values("organization_member_id", "role_id")

        result: dict[UUID, list[UUID]] = {}
        for membership in memberships:
            org_member_id = membership["organization_member_id"]
            if org_member_id not in result:
                result[org_member_id] = []
            result[org_member_id].append(membership["role_id"])
        return result

    def set_preloaded_dashboard_tiles(self, tiles: list[DashboardTile]):
        """
        Allows for speeding up insight-related permissions code
        """
        self._tiles = tiles

    @cached_property
    def preloaded_insight_dashboards(self) -> Optional[list[Dashboard]]:
        if self._tiles is None:
            return None

        dashboard_ids = {tile.dashboard_id for tile in self._tiles}
        return list(Dashboard.objects.filter(pk__in=dashboard_ids))

    def reset_insights_dashboard_cached_results(self):
        """
        Resets cached results for insights/dashboards. Useful for update methods.
        """
        self._dashboard_permissions = {}
        self._insight_permissions = {}


class UserTeamPermissions:
    def __init__(self, user_permissions: "UserPermissions", team: Team):
        self.p = user_permissions
        self.team = team

    @cached_property
    def effective_membership_level(self) -> Optional["OrganizationMembership.Level"]:
        """Return an effective membership level.
        None returned if the user has no explicit membership and organization access is too low for implicit membership.
        """

        membership = self.p.organization_memberships.get(self.team.organization_id)
        organization = self.p.get_organization(self.team.organization_id)
        return self.effective_membership_level_for_parent_membership(organization, membership)

    def effective_membership_level_for_parent_membership(
        self,
        organization: Optional[Organization],
        organization_membership: Optional[OrganizationMembership],
    ) -> Optional["OrganizationMembership.Level"]:
        if organization is None or organization_membership is None:
            return None

        if not organization.is_feature_available(AvailableFeature.ADVANCED_PERMISSIONS):
            return organization_membership.level

        # Use prefetched data to check team privacy and access
        access_controls = self.p._prefetched_access_controls.get(self.team.id, [])

        # Check if the team is private
        team_is_private = any(
            ac["resource_id"] == str(self.team.id)
            and ac["organization_member_id"] is None
            and ac["role_id"] is None
            and ac["access_level"] == "none"
            for ac in access_controls
        )

        # If team is not private, all organization members have access
        if not team_is_private:
            return cast("OrganizationMembership.Level", organization_membership.level)

        # For private teams, check if the user has specific access

        # Organization admins and owners always have access
        if organization_membership.level >= OrganizationMembership.Level.ADMIN:
            return cast("OrganizationMembership.Level", organization_membership.level)

        # Check for direct member access through AccessControl entries
        user_has_access = any(
            ac["resource_id"] == str(self.team.id)
            and ac["organization_member_id"] == organization_membership.id
            and ac["access_level"] in ["member", "admin"]
            for ac in access_controls
        )

        if user_has_access:
            return cast("OrganizationMembership.Level", organization_membership.level)

        # Check for role-based access
        user_roles = self.p._prefetched_role_memberships.get(organization_membership.id, [])

        if user_roles:
            role_has_access = any(
                ac["resource_id"] == str(self.team.id)
                and ac["role_id"] in user_roles
                and ac["access_level"] in ["member", "admin"]
                for ac in access_controls
            )

            if role_has_access:
                return cast("OrganizationMembership.Level", organization_membership.level)

        # No access found
        return None


class UserDashboardPermissions:
    def __init__(self, user_permissions: "UserPermissions", dashboard: Dashboard):
        self.p = user_permissions
        self.dashboard = dashboard

    @cached_property
    def effective_restriction_level(self) -> Dashboard.RestrictionLevel:
        return (
            self.dashboard.restriction_level
            if cast(Organization, self.p.current_organization).is_feature_available(
                AvailableFeature.ADVANCED_PERMISSIONS
            )
            else Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )

    @cached_property
    def can_restrict(self) -> bool:
        # Sync conditions with frontend hasInherentRestrictionsRights
        from posthog.models.organization import OrganizationMembership

        # The owner (aka creator) has full permissions
        if self.p.user.pk == self.dashboard.created_by_id:
            return True
        effective_project_membership_level = self.p.current_team.effective_membership_level
        return (
            effective_project_membership_level is not None
            and effective_project_membership_level >= OrganizationMembership.Level.ADMIN
        )

    @cached_property
    def effective_privilege_level(self) -> Dashboard.PrivilegeLevel:
        if (
            # Checks can be skipped if the dashboard in on the lowest restriction level
            self.effective_restriction_level == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
            # Users with restriction rights can do anything
            or self.can_restrict
        ):
            # Returning the highest access level if no checks needed
            return Dashboard.PrivilegeLevel.CAN_EDIT

        # We return lowest access level if there's no explicit privilege for this user
        return self.p.dashboard_privileges.get(self.dashboard.pk, Dashboard.PrivilegeLevel.CAN_VIEW)

    @cached_property
    def can_edit(self) -> bool:
        if self.effective_restriction_level < Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT:
            return True
        return self.effective_privilege_level >= Dashboard.PrivilegeLevel.CAN_EDIT


class UserInsightPermissions:
    def __init__(self, user_permissions: "UserPermissions", insight: Insight):
        self.p = user_permissions
        self.insight = insight

    @cached_property
    def effective_restriction_level(self) -> Dashboard.RestrictionLevel:
        if len(self.insight_dashboards) == 0:
            return Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT

        return max(self.p.dashboard(dashboard).effective_restriction_level for dashboard in self.insight_dashboards)

    @cached_property
    def effective_privilege_level(self) -> Dashboard.PrivilegeLevel:
        if len(self.insight_dashboards) == 0:
            return Dashboard.PrivilegeLevel.CAN_EDIT

        if any(self.p.dashboard(dashboard).can_edit for dashboard in self.insight_dashboards):
            return Dashboard.PrivilegeLevel.CAN_EDIT
        else:
            return Dashboard.PrivilegeLevel.CAN_VIEW

    @cached_property
    def insight_dashboards(self):
        # If we're in dashboard(s) and have sped up lookups
        if self.p.preloaded_insight_dashboards is not None:
            return self.p.preloaded_insight_dashboards

        dashboard_ids = set(
            DashboardTile.objects.filter(insight=self.insight.pk).values_list("dashboard_id", flat=True)
        )
        return list(Dashboard.objects.filter(pk__in=dashboard_ids))


class UserPermissionsSerializerMixin:
    """
    Mixin for getting easy access to UserPermissions within a mixin
    """

    context: Any

    @cached_property
    def user_permissions(self) -> UserPermissions:
        if "user_permissions" in self.context:
            return self.context["user_permissions"]
        return self.context["view"].user_permissions
