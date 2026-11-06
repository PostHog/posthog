from functools import cached_property
from typing import TYPE_CHECKING, Any, Optional, cast
from uuid import UUID

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.organization_caching import get_cached_organization_memberships

if TYPE_CHECKING:
    from products.access_control.backend.models.access_control import AccessControl


class UserPermissions:
    """
    Class responsible for figuring out user permissions in an efficient manner.

    Generally responsible for the following tasks:
    1. Calculating whether a user has access to the current team
    2. Calculating whether a user has access to other team(s)

    For efficiency sake the class _generally_ expects the current team/organization to be
    passed to it and will use it to skip certain lookups.
    """

    def __init__(self, user: User, team: Optional[Team] = None):
        self.user = user
        self._current_team = team

        self._team_permissions: dict[int, UserTeamPermissions] = {}

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

    @cached_property
    def teams_visible_for_user(self) -> list[Team]:
        candidate_teams = Team.objects.filter(organization_id__in=self.organizations.keys()).only(
            "pk", "organization_id", "project_id"
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
        memberships = get_cached_organization_memberships(self.user)
        return {membership.organization_id: membership for membership in memberships}

    @cached_property
    def _prefetched_access_controls(self) -> dict[int, list["AccessControl"]]:
        """Project AccessControl rows that can change this user's answer, grouped by team_id.

        Narrowed to the principal: a team's defaults, the user's own member rules, and rules
        of roles they hold. Rules naming another member or a role they do not hold cannot
        change the subject's resolution for this user, so loading them would only bloat the
        per-request working set.

        Returns model instances so `SubjectAccessControl.preload_access_controls` can seed its
        pool directly instead of reconstructing instances from dicts.
        """
        from django.db.models import Q  # noqa: PLC0415 - keeps the import local to the one caller

        from products.access_control.backend.models.access_control import AccessControl

        organization_ids = list(self.organizations.keys())
        user_role_ids = {
            role_id for role_ids in self._prefetched_role_ids_by_organization.values() for role_id in role_ids
        }
        principal_filter = Q(organization_member__user_id=self.user.pk) | Q(
            organization_member__isnull=True, role__isnull=True
        )
        if user_role_ids:
            principal_filter |= Q(role_id__in=user_role_ids)

        access_controls = AccessControl.objects.filter(
            team__organization_id__in=organization_ids, resource="project"
        ).filter(principal_filter)

        result: dict[int, list[AccessControl]] = {}
        for ac in access_controls:
            result.setdefault(ac.team_id, []).append(ac)
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
        role_memberships = RoleMembership.objects.filter(user=self.user).valid_for_authorization()
        for organization_id, role_id in role_memberships.values_list("role__organization_id", "role_id"):
            result.setdefault(organization_id, set()).add(role_id)
        return result


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

        # Admin/non-ACL bypasses happen here too so the caller skips the prefetch properties
        # that would otherwise query for data a short-circuited answer does not need.
        if not organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
            return UserTeamPermissions._capped_at_admin(organization_membership.level)
        if organization_membership.level >= OrganizationMembership.Level.ADMIN:
            return UserTeamPermissions._capped_at_admin(organization_membership.level)

        role_ids = self.p._prefetched_role_ids_by_organization.get(self.team.organization_id, set())
        return self.resolve_membership_level(
            organization=organization,
            organization_membership=organization_membership,
            team=self.team,
            user=self.p.user,
            preloaded_rows=self.p._prefetched_access_controls.get(self.team.id, []),
            subject_role_ids=[str(role_id) for role_id in role_ids],
        )

    @staticmethod
    def resolve_membership_level(
        *,
        organization: Organization,
        organization_membership: OrganizationMembership,
        team: Team,
        user: Optional[User] = None,
        preloaded_rows: Optional[list["AccessControl"]] = None,
        subject_role_ids: Optional[list[str]] = None,
    ) -> Optional["OrganizationMembership.Level"]:
        """Project access of one member of the team's organization, resolved through
        `SubjectAccessControl`. Delegating here keeps this resolver and the enforced API gate
        on one implementation instead of maintaining a parallel precedence rule for
        most-specific organizations.

        `preloaded_rows` and `subject_role_ids`, when given, seed the subject so the N
        resolutions a bulk caller does share one query for the team's rules and one query for
        the subject's roles rather than running N of each.
        """
        if not organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
            return UserTeamPermissions._capped_at_admin(organization_membership.level)

        # Admins and owners always have access, so skip the facade construction entirely.
        if organization_membership.level >= OrganizationMembership.Level.ADMIN:
            return UserTeamPermissions._capped_at_admin(organization_membership.level)

        from products.access_control.backend.facade.subject_access_control import (  # noqa: PLC0415 - circular at module import
            SubjectAccessControl,
        )

        subject = SubjectAccessControl(
            user=user if user is not None else organization_membership.user,
            team=team,
            org_membership=organization_membership,
            member=organization_membership,
        )
        if preloaded_rows is not None or subject_role_ids is not None:
            subject.preload_access_controls(preloaded_rows, subject_role_ids=subject_role_ids)

        level = subject.get_user_access_level(team)
        if level == "admin":
            return OrganizationMembership.Level.ADMIN
        if level == "member":
            return OrganizationMembership.Level.MEMBER
        return None

    @staticmethod
    def _capped_at_admin(organization_level: int) -> "OrganizationMembership.Level":
        """Project access tops out at admin, so an organization owner resolves to admin here rather
        than leaking `OWNER` out of a project-level resolver. No call site distinguishes the two —
        they all gate on `is not None`, `>= MEMBER` or `>= ADMIN`."""
        return min(cast("OrganizationMembership.Level", organization_level), OrganizationMembership.Level.ADMIN)


def user_can_access_team(user: User, team: Team) -> bool:
    """Whether the user has any access to the team. Membership of the team's organization is not
    enough on its own, because access control can restrict a project to some members."""
    return UserPermissions(user).team(team).effective_membership_level is not None


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
