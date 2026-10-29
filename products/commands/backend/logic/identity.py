"""Finds the projects a requester may act in, and the PostHog account that acts in each.

The channel finds the PostHog accounts linked to the person who asked. One person can have several,
for example a work and a personal one. Every link needed that person's approval on the channel's
side, so all of them belong to the person. The command picks the project, and the linked account
that is a member of it acts there.
"""

from collections.abc import Sequence
from typing import Literal

import structlog

from posthog.dataclasses import frozen
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.team import Team
from posthog.models.user import User
from posthog.user_permissions import UserPermissions

from products.security.backend.facade.api import access_refused
from products.security.backend.facade.contracts import SubjectInput
from products.security.backend.facade.enums import Surface

from .commands import ProjectMember

logger = structlog.get_logger(__name__)


@frozen
class Requester:
    # The candidate projects, each with a linked account that is a member of it. In the order of the
    # candidates, and within a project the channel's first choice first. Empty when no linked
    # account belongs to any of them.
    members: tuple[ProjectMember, ...]


@frozen
class UnresolvedRequester:
    reason: Literal["unlinked", "refused"]


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
    # whose email is outside its enforced verified domains, so a command must not reach those
    # projects either.
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
    # When two linked accounts are members of the same project, the one the channel lists first acts
    # there: on GitHub the most recently linked one, because the person linked it last.
    return tuple(
        ProjectMember(team_id=team.id, user_id=user.id)
        for team in teams
        for user in users
        if team.id in member_team_ids[user.id]
    )


def resolve_requester(users: list[User], team_ids: Sequence[int]) -> Requester | UnresolvedRequester:
    """The members among ``users`` (the channel's first choice first) of the candidate ``team_ids``."""
    if not users:
        return UnresolvedRequester(reason="unlinked")
    # The same rule that refuses an account's logins and API keys refuses its commands. Another
    # linked account can still log in, so it can still run commands.
    users = [
        user
        for user in users
        if not access_refused(
            SubjectInput(email=user.email, user_uuid=str(user.uuid)), Surface.APP, call_site="command"
        )
    ]
    if not users:
        return UnresolvedRequester(reason="refused")
    if len(users) > 1:
        logger.info("command_requester_has_several_accounts", account_count=len(users))
    return Requester(members=_project_members(users, team_ids))
