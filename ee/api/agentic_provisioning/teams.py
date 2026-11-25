"""Team resolution and creation for provisioning flows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction
from django.db.models import Q

from posthog.models.oauth import OAuthAccessToken
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.project import Project
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.user import User
from posthog.project_creation_limits import (
    PROJECT_CREATION_REQUIRES_ADMIN_MESSAGE,
    PROJECT_LIMIT_MESSAGES,
    member_can_create_projects,
    organization_project_limit_reached,
)
from posthog.scopes.checks import scopes_not_covered

from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action

from ee.api.agentic_provisioning.tokens import ensure_team_in_token_scopes, user_can_access_team

if TYPE_CHECKING:
    from collections.abc import Callable


class ProjectIdCollisionError(Exception):
    """Raised when a stripe_project_id is already in use by a team outside the caller's orgs."""

    def __init__(self, project_id: str) -> None:
        super().__init__(project_id)
        self.project_id = project_id


class ProjectCreationRefusedError(Exception):
    """Raised when the user may not create a project in the organization, or it holds its limit of projects."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


PROJECT_CREATION_FORBIDDEN_CODE = "forbidden"
PROJECT_LIMIT_REACHED_CODE = "project_limit_reached"

PROJECT_RENAME_SCOPE = "project:write"

UNCLAIMED_PROJECT_ID = Q(stripe_project_id__isnull=True) | Q(stripe_project_id="")


def _token_can_rename_project(access_token: OAuthAccessToken) -> bool:
    held_scopes = (access_token.scope or "").split()
    return "*" in held_scopes or not scopes_not_covered(held_scopes, [PROJECT_RENAME_SCOPE])


def _user_can_administer_team(user: User, team: Team) -> bool:
    return authorization.check(resource=Resource.project(team.id), action=Action.EDIT, subject=Subject(user_id=user.pk))


def _find_project_mapping(
    project_id: str, scoped_teams: list[int], access_token: OAuthAccessToken
) -> TeamProvisioningConfig | None:
    return (
        TeamProvisioningConfig.objects.filter(
            stripe_project_id=project_id,
            application=access_token.application,
            team__organization_id__in=Team.objects.filter(id__in=scoped_teams).values("organization_id"),
        )
        .select_related("team")
        .first()
    )


def _resolve_mapped_team(
    config: TeamProvisioningConfig,
    scoped_teams: list[int],
    user: User,
    access_token: OAuthAccessToken,
    enforce_ip_policy: Callable[[Team], None],
) -> tuple[Team | None, list[int]]:
    enforce_ip_policy(config.team)
    if not user_can_access_team(user, config.team):
        return None, scoped_teams
    return ensure_team_in_token_scopes(access_token, scoped_teams, config.team)


def _resolve_race_winner(
    project_id: str,
    scoped_teams: list[int],
    user: User,
    access_token: OAuthAccessToken,
    enforce_ip_policy: Callable[[Team], None],
) -> tuple[Team | None, list[int]]:
    race_winner = _find_project_mapping(project_id, scoped_teams, access_token)
    if race_winner:
        return _resolve_mapped_team(race_winner, scoped_teams, user, access_token, enforce_ip_policy)
    raise ProjectIdCollisionError(project_id)


def _claim_provisioned_team(
    project_id: str,
    base_team: Team,
    user: User,
    access_token: OAuthAccessToken,
) -> Team | None:
    """Bind project_id to the token's base team when this partner provisioned it and no project_id claims it yet.

    The account request already creates a project for the partner, so the first resource call
    reuses it instead of adding a second project to the organization. Only the base team, the
    project this user's account request created, can be claimed: another member's partner project
    in the token's scope is theirs, and a new project_id must not take it over or rename it.
    """
    if base_team.is_demo or not user_can_access_team(user, base_team):
        return None
    if Project.objects.filter(
        id=base_team.project_id, organization_id=base_team.organization_id, is_pending_deletion=True
    ).exists():
        return None

    # The update re-checks that the row is unclaimed, so two concurrent calls with different
    # project ids never bind the same team. The savepoint keeps a unique-constraint failure
    # from breaking an enclosing transaction.
    with transaction.atomic():
        claimed = TeamProvisioningConfig.objects.filter(
            UNCLAIMED_PROJECT_ID, application=access_token.application, team_id=base_team.id
        ).update(stripe_project_id=project_id)
    return base_team if claimed else None


def assert_user_can_create_project(user: User, organization: Organization) -> None:
    """Raise ProjectCreationRefusedError unless the user may create a project in the organization
    and the organization is under its project limit."""
    membership = OrganizationMembership.objects.filter(organization_id=organization.id, user=user).first()
    if membership is None or not member_can_create_projects(user, organization):
        raise ProjectCreationRefusedError(PROJECT_CREATION_FORBIDDEN_CODE, PROJECT_CREATION_REQUIRES_ADMIN_MESSAGE)

    reached_limit = organization_project_limit_reached(organization)
    if reached_limit is not None:
        raise ProjectCreationRefusedError(PROJECT_LIMIT_REACHED_CODE, PROJECT_LIMIT_MESSAGES[reached_limit])


def resolve_or_create_project_team(
    project_id: str,
    scoped_teams: list[int],
    user: User,
    configuration: dict,
    access_token: OAuthAccessToken,
    *,
    enforce_ip_policy: Callable[[Team], None],
) -> tuple[Team | None, list[int]]:
    """Look up, claim, or create a team for the given project_id.

    Uses TeamProvisioningConfig (DB-backed with unique constraint) for the
    project_id → team_id mapping. This ensures idempotency even across cache
    evictions and handles race conditions via IntegrityError.

    An unknown project_id first claims the token's base team when the partner
    provisioned it and no project_id claims it yet. Only when there is none does it create a project, and only
    when the user may create one and the organization is under its project limit.
    Raises ProjectCreationRefusedError otherwise.

    Returns (None, scoped_teams) when an existing team is resolved but the
    authenticated user lacks team-level access (honors advanced permissions
    / access controls on top of org membership).
    """
    existing = _find_project_mapping(project_id, scoped_teams, access_token)
    if existing:
        return _resolve_mapped_team(existing, scoped_teams, user, access_token, enforce_ip_policy)

    base_team = Team.objects.select_related("organization").get(id=scoped_teams[0])
    enforce_ip_policy(base_team)
    if not user_can_access_team(user, base_team):
        return None, scoped_teams

    try:
        claimed_team = _claim_provisioned_team(project_id, base_team, user, access_token)
    except IntegrityError:
        return _resolve_race_winner(project_id, scoped_teams, user, access_token, enforce_ip_policy)
    if claimed_team is not None:
        # Renaming a project needs a token that covers project:write and project admin access
        # everywhere else, so without both the claimed project keeps its existing name.
        if (
            "project_name" in configuration
            and _token_can_rename_project(access_token)
            and _user_can_administer_team(user, claimed_team)
        ):
            claimed_team.name = configuration["project_name"]
            # The projects API and project picker read Project.name, so it has to change with the
            # team. The id filter matches only when the claimed team is its project's main team.
            with transaction.atomic():
                claimed_team.save(update_fields=["name"])
                Project.objects.filter(id=claimed_team.id).update(name=claimed_team.name)
        return ensure_team_in_token_scopes(access_token, scoped_teams, claimed_team)

    # A concurrent request with the same project_id can claim the team first. Its mapping is
    # the answer, not a new project.
    concurrent_mapping = _find_project_mapping(project_id, scoped_teams, access_token)
    if concurrent_mapping:
        return _resolve_mapped_team(concurrent_mapping, scoped_teams, user, access_token, enforce_ip_policy)

    assert_user_can_create_project(user, base_team.organization)

    project_name = configuration.get("project_name", "Default project")
    new_team = Team.objects.create_with_data(
        initiating_user=user,
        organization=base_team.organization,
        name=project_name,
    )

    try:
        TeamProvisioningConfig.objects.update_or_create(
            team=new_team,
            defaults={"stripe_project_id": project_id, "application": access_token.application},
        )
    except IntegrityError:
        new_team.delete()
        return _resolve_race_winner(project_id, scoped_teams, user, access_token, enforce_ip_policy)

    return ensure_team_in_token_scopes(access_token, scoped_teams, new_team)
