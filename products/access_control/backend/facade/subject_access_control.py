from collections import defaultdict
from contextvars import ContextVar
from functools import cached_property
from typing import Any, Optional, cast

from django.db.models import F, Model, Q

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.user_access_control import (
    EE_AVAILABLE,
    NO_ACCESS_LEVEL,
    RESOURCE_INHERITANCE_MAP,
    RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS,
    AccessControlLevel,
    ResolvedAccess,
    UserAccessControl,
    _AccessControl,
    default_access_level,
    model_to_resource,
)
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import RoleMembership

# Per-question state for a resolution in progress, scoped to a `with` block rather than kept on the
# instance: the subject says whose access resolves; what to leave out for one question does not.
_masked_resource: ContextVar[Optional[APIScopeObject]] = ContextVar("subject_masked_resource", default=None)
_suspend_org_admin: ContextVar[bool] = ContextVar("subject_suspend_org_admin", default=False)


class SubjectAccessControl(UserAccessControl):
    """Resolves access for a subject rather than for the requesting user.

    The subject decides which rules count:
    - no subject: only the default rules (scoped to no member and no role) — what applies to everyone
    - member=...: the default rules, the member's own rules, and the rules of the member's roles
    - role_id=...: the default rules and that role's rules

    A member subject keeps the org-admin bypass when their membership level grants it; the
    other subjects never have it.

    For attribution and display (what does or would this subject have) — never for enforcing
    the requesting user's access, which is UserAccessControl's job. `user`/`team` are still the
    requesting user's context; the subject only changes whose rules resolve.
    """

    def __init__(
        self,
        user: User,
        team: Optional[Team] = None,
        organization_id: Optional[str] = None,
        *,
        org_membership: Optional[OrganizationMembership] = None,
        member: Optional[OrganizationMembership] = None,
        role_id: Optional[str] = None,
    ) -> None:
        super().__init__(user, team, organization_id)
        self._subject_member = member
        self._subject_role_id = role_id
        # The base resolvers first check that `user` is a member of the organization, and stop with
        # no access if not. A subject is in the organization by construction, so seed the membership
        # of `user` and the check passes without one lookup per subject.
        if org_membership is not None:
            self.__dict__["_organization_membership"] = org_membership

    @classmethod
    def for_member(
        cls, user_access_control: UserAccessControl, team: Team, member: OrganizationMembership
    ) -> "SubjectAccessControl":
        """The access of `member`, asked by the user of `user_access_control`."""
        return cls(
            user_access_control.user,
            team,
            org_membership=user_access_control._organization_membership,
            member=member,
        )

    @classmethod
    def for_role(cls, user_access_control: UserAccessControl, team: Team, role_id: str) -> "SubjectAccessControl":
        """The access of the role `role_id`, asked by the user of `user_access_control`."""
        return cls(
            user_access_control.user,
            team,
            org_membership=user_access_control._organization_membership,
            role_id=role_id,
        )

    @classmethod
    def for_default(cls, user_access_control: UserAccessControl, team: Team) -> "SubjectAccessControl":
        """The access the default rules give everyone, asked by the user of `user_access_control`."""
        return cls(user_access_control.user, team, org_membership=user_access_control._organization_membership)

    def stored_level(self, resource: APIScopeObject, resource_id: Optional[str]) -> Optional[AccessControlLevel]:
        """The level of the subject's own stored rule for a resource (resource-wide when
        resource_id is None), or None without one — the rule a settings UI edits, as opposed to
        what resolves for the subject."""
        filters = (
            self._access_controls_filters_for_object(resource, resource_id)
            if resource_id is not None
            else self._access_controls_filters_for_resource(resource)
        )
        return next((ac.access_level for ac in self._get_access_controls(filters) if self._is_subject_row(ac)), None)

    def inherited_access_for_object(self, obj: Model) -> Optional[ResolvedAccess]:
        """The access the subject would have if their override on this object were removed — the
        inherited level the UI shows next to "No override".

        Runs the subject's precheck (a member keeps their creator and org-admin bypasses even
        without the override) and then the same object walk, over the subject's rules with the
        subject's own rows on this object left out — so the answer cannot disagree with how
        access would actually be enforced.

        None when the subject is the object's own default and nothing sits above the object
        (the resources without resource-level controls, e.g. a project) — that None is
        load-bearing for the UI, which must not offer "No override" on a project's default. A
        member or role always has something to fall back to (the object's default, then the
        system default), so their answer is never None on that account.
        """
        resource = model_to_resource(obj)
        if not resource:
            return None
        if self._subject_member is None and self._subject_role_id is None:
            if resource in RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS:
                return None

        resolved, access = self._object_access_level_precheck(resource, self._is_creator(obj))
        if resolved:
            return access

        rows = [
            ac
            for ac in self._get_access_controls(self._access_controls_filters_for_object(resource, str(obj.id)))  # type: ignore
            if not self._is_subject_row(ac)
        ]
        return self._object_access_level_from_rows(
            resource, rows, fallback_parent_id=self._fallback_parent_id(obj, resource)
        )

    def inherited_access_for_resource(self, resource: APIScopeObject) -> Optional[ResolvedAccess]:
        """The access the subject would have to `resource` if their resource-wide override were
        removed — the resource-side twin of `inherited_access_for_object`.

        The same resource resolution (`access_level_for_resource`), with the subject's own rows
        for the resource left out of the fetch. `access_level_for_resource` fetches its own rows,
        so the mask applies at the fetch layer for the duration of this call only. No separate
        precheck, unlike the object twin: the org-admin bypass is part of `access_level_for_resource`
        itself, and there is no creator at resource level.
        """
        # The mask lives in a context variable for the duration of this call, not on the instance,
        # so it cannot leak into a later resolution
        token = _masked_resource.set(RESOURCE_INHERITANCE_MAP.get(resource, resource))
        try:
            return self.access_level_for_resource(resource)
        finally:
            _masked_resource.reset(token)

    def _get_access_controls(self, filters: dict) -> list[_AccessControl]:
        rows = super()._get_access_controls(filters)
        masked = _masked_resource.get()
        if masked is None or filters.get("resource") != masked:
            return rows
        return [ac for ac in rows if not self._is_subject_row(ac)]

    def has_project_scoped_access(self, team: Team) -> bool:
        """Whether the subject is granted access to the project by a rule — an explicit grant, a
        role, or the project default — as opposed to reaching it through the org-admin bypass.
        The visibility question: being an org admin is not being a member of the project."""
        token = _suspend_org_admin.set(True)
        try:
            return self.get_user_access_level(team) not in (None, NO_ACCESS_LEVEL)
        finally:
            _suspend_org_admin.reset(token)

    def _applies_to_subject(self, access_control: _AccessControl, role_ids: frozenset[str]) -> bool:
        """In-memory twin of this class's `_filter_options`: whether a row is one the subject's
        resolution may see (a default rule, the subject's own rule, or one of their roles, given as
        `role_ids`). Broader than `_is_subject_row`, which picks out only the subject's own rules."""
        if access_control.organization_member_id is None and access_control.role_id is None:
            return True
        if self._subject_member is not None and access_control.organization_member_id == self._subject_member.id:
            return access_control.role_id is None
        return access_control.organization_member_id is None and str(access_control.role_id) in role_ids

    @cached_property
    def team_access_controls(self) -> list[_AccessControl]:
        """Every rule on the team, un-narrowed — the pool this subject resolves from, and that
        sibling subjects for the same team are seeded from (`preload_access_controls`). The same
        query as `_cached_access_controls` minus its per-principal narrowing, which each subject
        applies in memory instead: one query for many subjects rather than one per subject."""
        assert self._team is not None
        if not EE_AVAILABLE:
            return []
        return list(
            AccessControl.objects.annotate(_team_organization_id=F("team__organization_id")).filter(
                team_id=self._team.id
            )
        )

    def preload_access_controls(
        self,
        rows: Optional[list[_AccessControl]] = None,
        *,
        subject_role_ids: Optional[list[str]] = None,
    ) -> None:
        """Seed the team pool of this subject (`_cached_access_controls`) from `rows`, so that many
        subjects share one query instead of each reading the database.

        `rows` is a pool that is already loaded: the `team_access_controls` of a sibling subject, or
        the caller's own query. Without `rows`, this subject loads the pool itself. The pool is
        narrowed to the subject in memory first, exactly as `_filter_options` narrows it in the
        query that the pool replaces.

        This method seeds the pool. The base class's `preload_*` methods do the other half: they
        pre-answer specific lookups from the pool, and they never write the pool. Only
        `for_team_ids` writes it, in the same way as here. A `cached_property` is pre-filled by
        writing its slot in `__dict__`.

        For a member subject, `subject_role_ids` seeds the member's role ids in the same way, when
        the caller already prefetched them, so N subjects do not read them N times.
        """
        assert self._team is not None
        if subject_role_ids is not None:
            self.__dict__["_user_role_ids"] = list(subject_role_ids) if self.rbac_supported else []
        # Team-scoped lookups are served from _cached_access_controls, so that is what to seed
        pool = rows if rows is not None else self.team_access_controls
        role_ids = frozenset(str(role_id) for role_id in self._user_role_ids)
        self.__dict__["_cached_access_controls"] = [ac for ac in pool if self._applies_to_subject(ac, role_ids)]

    def _is_creator(self, obj: Model) -> bool:
        """The subject created the object, not the requesting user. A role and the default subject
        are not people, so they never created anything."""
        return self._subject_member is not None and getattr(obj, "created_by", None) == self._subject_member.user

    def _is_subject_row(self, access_control: _AccessControl) -> bool:
        """Whether this row is the subject's own — the kind of rule "No override" would remove."""
        if self._subject_member is not None:
            return access_control.organization_member_id == self._subject_member.id
        if self._subject_role_id is not None:
            return str(access_control.role_id) == str(self._subject_role_id)
        return access_control.organization_member_id is None and access_control.role_id is None

    @cached_property
    def _user_role_ids(self) -> list[str]:
        # Role rules are inert without the entitlement, for a member's roles and for a role subject alike
        if not self.rbac_supported:
            return []
        if self._subject_member is not None:
            return list(
                cast(Any, self._subject_member.user)
                .role_memberships.filter(role__organization_id=self._organization_id)
                .values_list("role_id", flat=True)
            )
        return [self._subject_role_id] if self._subject_role_id else []

    def _filter_options(self, filters: dict[str, Any]) -> Q:
        q = Q(**filters, organization_member=None, role=None)
        if self._subject_member is not None:
            q |= Q(**filters, organization_member=self._subject_member, role=None)
        if self._user_role_ids:
            q |= Q(**filters, organization_member=None, role__in=self._user_role_ids)
        return q

    @property
    def is_organization_admin(self) -> bool:
        if _suspend_org_admin.get():
            return False
        return bool(self._subject_member and self._subject_member.level >= OrganizationMembership.Level.ADMIN)


def get_project_scoped_visible_membership_ids(
    organization: Organization, requesting_membership: OrganizationMembership
) -> Optional[set[str]]:
    """Membership ids a restricted (non-org-admin) member may see: their own, plus members with
    project-scoped access (explicit grant, role, or project default — no org-admin bypass) to any
    project the requester has access to. Returns None when every member is visible, so callers can
    skip filtering without materializing the roster."""
    # Without the entitlement, stale AccessControl rules in the DB must be ignored, not enforced —
    # every project falls back to its default access, so every member is visible.
    if not organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return None

    teams = list(organization.teams.all())
    team_ids = [team.id for team in teams]
    role_based_access = organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS)

    # One query for every project rule in the org. Each (team, member) resolution below is served
    # from this pool in memory, so the walk runs per pair without a query per pair. A project rule
    # is an object rule on the team (resource_id = the team's id) — the shape enforcement reads.
    project_rows = list(
        AccessControl.objects.filter(
            team_id__in=team_ids, resource="project", resource_id__in=[str(team_id) for team_id in team_ids]
        )
    )
    # Grouped by team, so resolving a (team, member) pair scans that team's rules rather than the
    # organization's — the scan runs once per pair, and an organization with many teams has many
    # more project rules than any one team does
    rows_by_team: dict[int, list[_AccessControl]] = defaultdict(list)
    for ac in project_rows:
        rows_by_team[ac.team_id].append(ac)

    default_by_team: dict[int, AccessControlLevel] = {}
    member_overrides: dict[tuple[int, str], AccessControlLevel] = {}
    role_overrides: dict[tuple[int, str], AccessControlLevel] = {}
    for ac in project_rows:
        if ac.organization_member_id is None and ac.role_id is None:
            default_by_team[ac.team_id] = ac.access_level
        elif ac.organization_member_id:
            member_overrides[(ac.team_id, str(ac.organization_member_id))] = ac.access_level
        elif ac.role_id and role_based_access:
            role_overrides[(ac.team_id, str(ac.role_id))] = ac.access_level

    # A member's effective access can differ from the team default only if a rule mentions them —
    # directly, or via a role they hold. Everyone else has exactly the default outcome, so only
    # rule-mentioned candidates need individual evaluation.
    candidate_role_ids: dict[str, list[str]] = defaultdict(list)
    referenced_role_ids = {role_id for (_, role_id) in role_overrides}
    if referenced_role_ids:
        for rm in RoleMembership.objects.filter(role_id__in=referenced_role_ids):
            if rm.organization_member_id:
                candidate_role_ids[str(rm.organization_member_id)].append(str(rm.role_id))
    candidate_ids = {membership_id for (_, membership_id) in member_overrides} | set(candidate_role_ids)

    requester_id = str(requesting_membership.id)
    memberships_by_id = {
        str(m.id): m
        for m in OrganizationMembership.objects.filter(
            organization=organization, id__in=[*candidate_ids, requester_id]
        ).select_related("user")
    }
    teams_by_id = {team.id: team for team in teams}

    def has_scoped_access(team_id: int, membership_id: str) -> bool:
        # The project walk enforcement runs (explicit member/role rows win over the team default),
        # for this member as the subject, answered from the pool above. The org-admin bypass is
        # ignored: being an admin is not being granted anything on this project.
        team = teams_by_id[team_id]
        subject = SubjectAccessControl(
            requesting_membership.user,
            team,
            org_membership=requesting_membership,
            member=memberships_by_id[membership_id],
        )
        # The member's roles were loaded above for candidate narrowing (only roles a project rule
        # names can matter, and none count without the entitlement) — hand them over rather than
        # let each subject query them again
        subject.preload_access_controls(
            rows_by_team[team_id], subject_role_ids=candidate_role_ids.get(membership_id, [])
        )
        return subject.has_project_scoped_access(team)

    accessible_team_ids = [team_id for team_id in team_ids if has_scoped_access(team_id, requester_id)]

    open_team_accessible = any(
        default_by_team.get(team_id, default_access_level("project")) != NO_ACCESS_LEVEL
        for team_id in accessible_team_ids
    )
    if open_team_accessible:
        # An open team makes every non-candidate visible; a candidate is hidden only if every
        # accessible team denies them (dead branch under max-wins, real under more-specific-wins).
        hidden = {
            membership_id
            for membership_id in candidate_ids
            if all(not has_scoped_access(team_id, membership_id) for team_id in accessible_team_ids)
        }
        if not hidden:
            return None
        all_ids = {
            str(membership_id)
            for membership_id in OrganizationMembership.objects.filter(organization=organization).values_list(
                "id", flat=True
            )
        }
        return (all_ids - hidden) | {requester_id}

    # Only private teams are accessible: non-candidates have the "none" default everywhere.
    visible = {requester_id}
    for membership_id in candidate_ids:
        if any(has_scoped_access(team_id, membership_id) for team_id in accessible_team_ids):
            visible.add(membership_id)
    return visible


def restricted_visible_membership_ids(organization: Organization, user: User) -> Optional[set[str]]:
    """Membership ids `user` may see when the org restricts member list visibility, or None when
    unrestricted (the setting is enabled, or the user is an org admin)."""
    if organization.members_can_see_org_members:
        return None
    membership = OrganizationMembership.objects.filter(organization=organization, user_id=user.id).first()
    if membership is None:
        return set()
    if membership.level >= OrganizationMembership.Level.ADMIN:
        return None
    return get_project_scoped_visible_membership_ids(organization, membership)
