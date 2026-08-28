from functools import cached_property
from typing import Any, Optional, cast
from uuid import UUID

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User

from products.dashboards.backend.facade.enums import PrivilegeLevel, RestrictionLevel
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight


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
    def dashboard_privileges(self) -> dict[int, PrivilegeLevel]:
        try:
            from ee.models import DashboardPrivilege

            rows = DashboardPrivilege.objects.filter(user=self.user).values_list("dashboard_id", "level")
            return {dashboard_id: cast(PrivilegeLevel, level) for dashboard_id, level in rows}
        except ImportError:
            return {}

    @cached_property
    def _prefetched_access_controls(self) -> dict[int, list[dict[str, Any]]]:
        """
        Prefetch all AccessControl entries for teams in user's organizations.
        Returns a dict mapping team_id to list of access control entries.
        """
        from products.access_control.backend.models.access_control import AccessControl

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
    def _prefetched_role_ids_by_organization(self) -> dict[UUID, set[UUID]]:
        """Prefetch the ids of every role the user holds, grouped by the role's organization.

        Grouped by the role's organization rather than by the `organization_member` FK for two
        reasons. That FK is nullable and legacy rows have it NULL (see `RoleMembershipViewSet.
        safely_get_queryset`), so grouping by it silently drops those rows' role rules, including
        denials. And the organization is the authorization boundary a role must not cross: an
        AccessControl row can name a role belonging to a different organization, so callers have to
        look roles up under the organization of the team being resolved.
        """
        from products.access_control.backend.models.role import RoleMembership

        result: dict[UUID, set[UUID]] = {}
        for organization_id, role_id in RoleMembership.objects.filter(user=self.user).values_list(
            "role__organization_id", "role_id"
        ):
            result.setdefault(organization_id, set()).add(role_id)
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
        # nosemgrep: idor-lookup-without-team (IDs from internal FK query)
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

        # The member arm below resolves rules against the passed membership, while roles are looked
        # up under `self.p.user`. A mismatched pair would mix one user's roles into another user's
        # resolution, so require the caller to pair them.
        if organization_membership.user_id != self.p.user.pk:
            raise ValueError("organization_membership must belong to the UserPermissions principal")

        if not organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
            return self._capped_at_admin(organization_membership.level)

        # Project rules for this team, from prefetched data
        access_controls = [
            ac
            for ac in self.p._prefetched_access_controls.get(self.team.id, [])
            if ac["resource_id"] == str(self.team.id)
        ]

        # Organization admins and owners always have access
        if organization_membership.level >= OrganizationMembership.Level.ADMIN:
            return self._capped_at_admin(organization_membership.level)

        # Role-backed project AccessControl rows only take effect if the organization has
        # the ROLE_BASED_ACCESS feature — same gate as the UI's "Roles" block on the
        # project access settings page (and as resource-level role overrides).
        role_based_access_supported = organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS)
        user_roles = self.p._prefetched_role_ids_by_organization.get(self.team.organization_id, set())

        # Rules naming this user — directly, or through a role they hold. These decide on their
        # own: the highest of them wins, and an explicit "none" is a denial rather than a miss
        # that falls through to the team default. Same explicit-wins precedence as
        # `_object_access_level_from_rows` in `products/access_control/backend/facade/user_access_control.py`.
        explicit_access_levels = [
            ac["access_level"]
            for ac in access_controls
            if ac["organization_member_id"] == organization_membership.id
            or (role_based_access_supported and ac["role_id"] is not None and ac["role_id"] in user_roles)
        ]

        if explicit_access_levels:
            return self._highest_membership_level(explicit_access_levels)

        # Fall back to the default access level for this team (applies to all org members)
        default_access_level = next(
            (
                ac["access_level"]
                for ac in access_controls
                if ac["organization_member_id"] is None and ac["role_id"] is None
            ),
            None,
        )

        if default_access_level is not None:
            return self._highest_membership_level([default_access_level])

        # No access control row in the database, admin by default. See: `default_access_level()` in `products/access_control/backend/facade/user_access_control.py`
        return OrganizationMembership.Level.ADMIN

    @staticmethod
    def _capped_at_admin(organization_level: int) -> "OrganizationMembership.Level":
        """Project access tops out at admin, so an organization owner resolves to admin here rather
        than leaking `OWNER` out of a project-level resolver. No call site distinguishes the two —
        they all gate on `is not None`, `>= MEMBER` or `>= ADMIN`."""
        return min(cast("OrganizationMembership.Level", organization_level), OrganizationMembership.Level.ADMIN)

    @staticmethod
    def _highest_membership_level(access_levels: list[str]) -> Optional["OrganizationMembership.Level"]:
        """Highest of the given project access levels as a membership level. None for "none", which
        is a denial — callers gate on `effective_membership_level is not None`."""
        if "admin" in access_levels:
            return OrganizationMembership.Level.ADMIN
        if "member" in access_levels:
            return OrganizationMembership.Level.MEMBER
        return None


class UserDashboardPermissions:
    def __init__(self, user_permissions: "UserPermissions", dashboard: Dashboard):
        self.p = user_permissions
        self.dashboard = dashboard

    @cached_property
    def effective_restriction_level(self) -> RestrictionLevel:
        return (
            RestrictionLevel(self.dashboard.restriction_level)
            if cast(Organization, self.p.current_organization).is_feature_available(AvailableFeature.ACCESS_CONTROL)
            else RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
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
    def effective_privilege_level(self) -> PrivilegeLevel:
        if (
            # Checks can be skipped if the dashboard in on the lowest restriction level
            self.effective_restriction_level == RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
            # Users with restriction rights can do anything
            or self.can_restrict
        ):
            # Returning the highest access level if no checks needed
            return PrivilegeLevel.CAN_EDIT

        # We return lowest access level if there's no explicit privilege for this user
        return self.p.dashboard_privileges.get(self.dashboard.pk, PrivilegeLevel.CAN_VIEW)

    @cached_property
    def can_edit(self) -> bool:
        if self.effective_restriction_level < RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT:
            return True
        return self.effective_privilege_level >= PrivilegeLevel.CAN_EDIT


class UserInsightPermissions:
    def __init__(self, user_permissions: "UserPermissions", insight: Insight):
        self.p = user_permissions
        self.insight = insight

    @cached_property
    def effective_restriction_level(self) -> RestrictionLevel:
        if len(self.insight_dashboards) == 0:
            return RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT

        return max(self.p.dashboard(dashboard).effective_restriction_level for dashboard in self.insight_dashboards)

    @cached_property
    def effective_privilege_level(self) -> PrivilegeLevel:
        if len(self.insight_dashboards) == 0:
            return PrivilegeLevel.CAN_EDIT

        if any(self.p.dashboard(dashboard).can_edit for dashboard in self.insight_dashboards):
            return PrivilegeLevel.CAN_EDIT
        else:
            return PrivilegeLevel.CAN_VIEW

    @cached_property
    def insight_dashboards(self):
        # If we're in dashboard(s) and have sped up lookups
        if self.p.preloaded_insight_dashboards is not None:
            return self.p.preloaded_insight_dashboards

        dashboard_ids = set(
            DashboardTile.objects.filter(insight=self.insight.pk).values_list("dashboard_id", flat=True)
        )
        # nosemgrep: idor-lookup-without-team (IDs from internal FK query)
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


def user_is_team_admin(user: User, team: Team | int) -> bool:
    team_obj: Team
    if isinstance(team, int):
        try:
            team_obj = Team.objects.get(id=team)
        except Team.DoesNotExist:
            return False
    else:
        team_obj = team
    level = UserPermissions(user).team(team_obj).effective_membership_level
    return level is not None and level >= OrganizationMembership.Level.ADMIN
