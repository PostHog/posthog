"""Which projects each organization member can reach, and why.

The organization members page asks this across every project at once. The project settings
page answers it for one project (`access_control_members`); this walks the same resolution
per (member, project) pair with the rules of each project loaded once.
"""

from collections import defaultdict
from dataclasses import replace
from typing import Optional
from uuid import UUID

from django.db.models import Prefetch

from posthog.constants import INTERNAL_BOT_EMAIL_SUFFIX
from posthog.dataclasses import frozen
from posthog.models import Organization, OrganizationMembership, Team, User

from products.access_control.backend.facade.resolution_preview import deciding_subject_row
from products.access_control.backend.facade.subject_access_control import (
    SubjectAccessControl,
    get_project_scoped_visible_membership_ids,
)
from products.access_control.backend.facade.user_access_control import AccessControlLevel, ResolvedAccess
from products.access_control.backend.models.role import Role, RoleMembership


@frozen
class ProjectAccessEntry:
    team_id: int
    team_name: str
    access_level: AccessControlLevel
    # None only when the member has no organization membership to resolve from
    resolved: Optional[ResolvedAccess]
    # The role or membership id whose row decided, so a display can link to it
    subject_id: Optional[str]


@frozen
class MemberProjectAccess:
    organization_membership_id: UUID
    projects: tuple[ProjectAccessEntry, ...]


def _visible_memberships(
    organization: Organization, requester: OrganizationMembership, member_id: Optional[UUID]
) -> list[OrganizationMembership]:
    memberships = (
        OrganizationMembership.objects.filter(organization=organization, user__is_active=True)
        .exclude(user__email__endswith=INTERNAL_BOT_EMAIL_SUFFIX)
        .select_related("user")
        .prefetch_related(Prefetch("role_memberships", queryset=RoleMembership.objects.valid_for_authorization()))
        .order_by("user__first_name", "user__email")
    )
    if member_id is not None:
        memberships = memberships.filter(id=member_id)
    # The same roster the members list shows: a restricted member sees only their project peers
    if not organization.members_can_see_org_members and requester.level < OrganizationMembership.Level.ADMIN:
        visible_ids = get_project_scoped_visible_membership_ids(organization, requester)
        if visible_ids is not None:
            memberships = memberships.filter(id__in=visible_ids)
    return list(memberships)


def _with_deciding_subject(
    subject: SubjectAccessControl, access: ResolvedAccess, role_names: dict[str, str], member_names: dict[str, str]
) -> tuple[ResolvedAccess, Optional[str]]:
    row = deciding_subject_row(subject, access)
    if row is None:
        return access, None
    if row.role_id is not None:
        role_id = str(row.role_id)
        return replace(access, subject_name=role_names.get(role_id)), role_id
    member_id = str(row.organization_member_id)
    return replace(access, subject_name=member_names.get(member_id)), member_id


def member_project_access(
    organization: Organization,
    requester: OrganizationMembership,
    user: User,
    *,
    member_id: Optional[UUID] = None,
) -> list[MemberProjectAccess]:
    """Every visible member's resolved access to every project the requester can reach.

    `requester` is `user`'s membership of `organization`. Projects the requester cannot access
    are left out, so a member never learns about projects hidden from them.
    """
    memberships = _visible_memberships(organization, requester, member_id)
    if not memberships:
        return []

    teams = list(Team.objects.filter(organization=organization).order_by("name", "id"))
    role_names = {str(role.id): role.name for role in Role.objects.filter(organization=organization)}
    member_names = {str(membership.id): membership.user.get_full_name() for membership in memberships}
    role_ids_by_membership = {
        membership.id: [str(rm.role_id) for rm in membership.role_memberships.all()] for membership in memberships
    }

    entries: dict[UUID, list[ProjectAccessEntry]] = defaultdict(list)
    for team in teams:
        team.organization = organization
        # The requester as their own subject: their rules, roles and admin bypass, seeded with
        # the membership already loaded so the check costs no query per project
        requester_access = SubjectAccessControl(user, team, org_membership=requester, member=requester)
        if not requester_access.check_access_level_for_object(team, "member"):
            continue

        # The first subject loads the team's rules once; the rest are seeded from its pool
        team_rows = None
        for membership in memberships:
            subject = SubjectAccessControl(user, team, org_membership=requester, member=membership)
            subject.preload_access_controls(team_rows, subject_role_ids=role_ids_by_membership[membership.id])
            if team_rows is None:
                team_rows = subject.team_access_controls

            resolved = subject._resolved_object_access(team)
            subject_id = None
            if resolved is not None:
                resolved, subject_id = _with_deciding_subject(subject, resolved, role_names, member_names)
            entries[membership.id].append(
                ProjectAccessEntry(
                    team_id=team.id,
                    team_name=team.name,
                    access_level=resolved.access_level if resolved else "none",
                    resolved=resolved,
                    subject_id=subject_id,
                )
            )

    return [
        MemberProjectAccess(organization_membership_id=membership.id, projects=tuple(entries[membership.id]))
        for membership in memberships
    ]
