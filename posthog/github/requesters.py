"""Who a person asking from GitHub is in PostHog, and which projects they may act in.

Every product that starts work on behalf of a GitHub user resolves them here, so one set of rules
decides who may start a run. The steps are:

1. ``users_linked_to_github_account``: the PostHog accounts linked to the GitHub account, matched on
   GitHub's numeric user id, never on the login. A login can be renamed and then claimed by someone
   else, but the id stays with the account. Only identities that GitHub itself confirmed to PostHog
   count: the GitHub account a user connected in PostHog, or the one they log in with. A login typed
   into a profile or saved on a project integration does not.
2. ``resolve_requester``: the linked accounts that the security rules allow, and the candidate
   projects each one is a member of. Channels that link accounts another way, such as Slack, call it
   with their own accounts.
3. ``members_with_resource_access``: the members that also have the access a product declares, in
   PostHog access control.

One person can have several linked accounts, for example a work and a personal one. Every link
needed that person's approval, so all of them belong to the person. The caller picks the project,
and the linked account that is a member of it acts there.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

import structlog
from social_django.models import UserSocialAuth

from posthog.dataclasses import frozen
from posthog.github.project_members import ProjectMember
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.permissions import UserAccessControl
from posthog.scopes import APIScopeObject
from posthog.user_permissions import UserPermissions

from products.security.backend.facade.api import access_refused
from products.security.backend.facade.contracts import SubjectInput
from products.security.backend.facade.enums import Surface

logger = structlog.get_logger(__name__)

GITHUB_WRITE_PERMISSIONS = frozenset({"admin", "maintain", "write"})


@frozen
class Requester:
    # The candidate projects, each with a linked account that is a member of it. In the order of the
    # candidates, and within a project the caller's first choice first. Empty when no linked
    # account belongs to any of them.
    members: tuple[ProjectMember, ...]


@frozen
class UnresolvedRequester:
    reason: Literal["unlinked", "refused"]


def users_linked_to_github_account(github_user_id: int) -> list[User]:
    """The active users linked to the GitHub account, most recently linked first."""
    links = [
        *UserIntegration.objects.filter(
            kind=UserIntegration.IntegrationKind.GITHUB,
            # The id arrives as a JSON number from the GitHub OAuth flow. Older rows may hold a string.
            config__github_user__id__in=[github_user_id, str(github_user_id)],
        ).values_list("user_id", "created_at"),
        *UserSocialAuth.objects.filter(provider="github", uid=str(github_user_id)).values_list("user_id", "created"),
    ]
    linked_at: dict[int, datetime] = {}
    for user_id, created_at in links:
        linked_at[user_id] = max(created_at, linked_at.get(user_id, created_at))
    users = User.objects.filter(id__in=linked_at, is_active=True)
    return sorted(users, key=lambda user: (linked_at[user.id], user.id), reverse=True)


def _is_member(permissions: UserPermissions, team: Team) -> bool:
    if permissions.team(team).effective_membership_level is None:
        return False
    # A child environment without its own access rows defaults open while the parent project
    # denies the user, so the parent decides too.
    parent = team.parent_team
    return parent is None or permissions.team(parent).effective_membership_level is not None


def _member_team_ids(user: User, teams: list[Team]) -> set[int]:
    permissions = UserPermissions(user)
    organizations = {team.organization_id: team.organization for team in teams}
    # The product APIs refuse an organization that is pending deletion or inactive, and a member
    # whose email is outside its enforced verified domains, so a request from GitHub must not reach
    # those projects either.
    blocked_organization_ids = {
        organization_id
        for organization_id, organization in organizations.items()
        if organization.is_pending_deletion
        or not organization.is_active
        or OrganizationDomain.objects.is_email_blocked_by_domain_enforcement(user.email, organization)
    }
    return {
        team.id
        for team in teams
        if team.organization_id not in blocked_organization_ids and _is_member(permissions, team)
    }


def _project_members(users: list[User], team_ids: Sequence[int]) -> tuple[ProjectMember, ...]:
    teams_by_id = Team.objects.select_related("organization", "parent_team__organization").in_bulk(team_ids)
    teams = [teams_by_id[team_id] for team_id in team_ids if team_id in teams_by_id]
    member_team_ids = {user.id: _member_team_ids(user, teams) for user in users}
    # When two linked accounts are members of the same project, the one the caller lists first acts
    # there: on GitHub the most recently linked one, because the person linked it last.
    return tuple(
        ProjectMember(team_id=team.id, user_id=user.id)
        for team in teams
        for user in users
        if team.id in member_team_ids[user.id]
    )


def resolve_requester(users: list[User], team_ids: Sequence[int], *, call_site: str) -> Requester | UnresolvedRequester:
    """The members among ``users`` (the caller's first choice first) of the candidate ``team_ids``."""
    if not users:
        return UnresolvedRequester(reason="unlinked")
    # The same rule that refuses an account's logins and API keys refuses its requests. Another
    # linked account can still log in, so it can still ask.
    users = [
        user
        for user in users
        if not access_refused(
            SubjectInput(email=user.email, user_uuid=str(user.uuid)), Surface.APP, call_site=call_site
        )
    ]
    if not users:
        return UnresolvedRequester(reason="refused")
    if len(users) > 1:
        logger.info("requester_has_several_accounts", account_count=len(users))
    return Requester(members=_project_members(users, team_ids))


AccessLevel = Literal["viewer", "editor", "manager"]


def members_with_resource_access(
    members: tuple[ProjectMember, ...], users: Sequence[User], *, resource: APIScopeObject, level: AccessLevel
) -> tuple[ProjectMember, ...]:
    users_by_id = {user.id: user for user in users}
    # Products keep their rows, and their access rules, on the parent project.
    effective_team_ids = {member.team_id: resolve_effective_team_id(member.team_id) for member in members}
    teams = Team.objects.in_bulk(set(effective_team_ids.values()))

    def has_access(member: ProjectMember) -> bool:
        team = teams.get(effective_team_ids[member.team_id])
        if team is None:
            return False
        access_control = UserAccessControl(
            user=users_by_id[member.user_id], team=team, organization_id=str(team.organization_id)
        )
        return access_control.check_access_level_for_resource(resource, level)

    return tuple(member for member in members if has_access(member))
