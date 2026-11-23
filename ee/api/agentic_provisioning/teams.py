"""Team resolution and creation for provisioning flows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction
from django.db.models import Q

from posthog.models.oauth import OAuthAccessToken
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.user import User
from posthog.project_creation_limits import (
    PROJECT_CREATION_REQUIRES_ADMIN_MESSAGE,
    PROJECT_LIMIT_MESSAGES,
    membership_can_create_projects,
    organization_project_limit_reached,
)

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

UNCLAIMED_PROJECT_ID = Q(stripe_project_id__isnull=True) | Q(stripe_project_id="")


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
    scoped_teams: list[int],
    user: User,
    access_token: OAuthAccessToken,
    enforce_ip_policy: Callable[[Team], None],
) -> Team | None:
    """Bind project_id to a team in the token's scope that this partner provisioned and no project_id claims yet.

    The account request already creates a project for the partner, so the first resource call
    reuses it instead of adding a second project to the organization.
    """
    candidates = (
        TeamProvisioningConfig.objects.filter(
            UNCLAIMED_PROJECT_ID,
            application=access_token.application,
            team_id__in=scoped_teams,
            team__is_demo=False,
        )
        .exclude(team__project__is_pending_deletion=True)
        .select_related("team")
        .order_by("team_id")
    )
    for config in candidates:
        enforce_ip_policy(config.team)
        if not user_can_access_team(user, config.team):
            continue

        # The update re-checks that the row is unclaimed, so two concurrent calls with different
        # project ids never bind the same team. The savepoint keeps a unique-constraint failure
        # from breaking an enclosing transaction.
        with transaction.atomic():
            claimed = TeamProvisioningConfig.objects.filter(UNCLAIMED_PROJECT_ID, team_id=config.team_id).update(
                stripe_project_id=project_id
            )
        if claimed:
            return config.team
    return None


def _assert_user_can_create_project(user: User, team: Team) -> None:
    organization = team.organization
    membership = OrganizationMembership.objects.filter(organization_id=organization.id, user=user).first()
    if membership is None or not membership_can_create_projects(organization, membership.effective_level):
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

    An unknown project_id first claims the partner's unclaimed project in the
    token's scope. Only when there is none does it create a project, and only
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
        claimed_team = _claim_provisioned_team(project_id, scoped_teams, user, access_token, enforce_ip_policy)
    except IntegrityError:
        return _resolve_race_winner(project_id, scoped_teams, user, access_token, enforce_ip_policy)
    if claimed_team is not None:
        return ensure_team_in_token_scopes(access_token, scoped_teams, claimed_team)

    _assert_user_can_create_project(user, base_team)

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
