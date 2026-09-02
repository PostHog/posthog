"""Team resolution and creation for provisioning flows."""

from __future__ import annotations

from django.db import IntegrityError

from posthog.models.oauth import OAuthAccessToken
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.user import User

from ee.api.agentic_provisioning.tokens import ensure_team_in_token_scopes, user_can_access_team


class ProjectIdCollisionError(Exception):
    """Raised when a stripe_project_id is already in use by a team outside the caller's orgs."""

    def __init__(self, project_id: str) -> None:
        super().__init__(project_id)
        self.project_id = project_id


def resolve_or_create_project_team(
    project_id: str,
    scoped_teams: list[int],
    user: User,
    configuration: dict,
    access_token: OAuthAccessToken,
) -> tuple[Team | None, list[int]]:
    """Look up or create a team for the given project_id.

    Uses TeamProvisioningConfig (DB-backed with unique constraint) for the
    project_id → team_id mapping. This ensures idempotency even across cache
    evictions and handles race conditions via IntegrityError.

    Returns (None, scoped_teams) when an existing team is resolved but the
    authenticated user lacks team-level access (honors advanced permissions
    / access controls on top of org membership).
    """
    existing = (
        TeamProvisioningConfig.objects.filter(
            stripe_project_id=project_id,
            application=access_token.application,
            team__organization_id__in=Team.objects.filter(id__in=scoped_teams).values("organization_id"),
        )
        .select_related("team")
        .first()
    )
    if existing:
        if not user_can_access_team(user, existing.team):
            return None, scoped_teams
        return ensure_team_in_token_scopes(access_token, scoped_teams, existing.team)

    base_team = Team.objects.get(id=scoped_teams[0])
    if not user_can_access_team(user, base_team):
        return None, scoped_teams

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
        race_winner = (
            TeamProvisioningConfig.objects.filter(
                stripe_project_id=project_id,
                application=access_token.application,
                team__organization_id__in=Team.objects.filter(id__in=scoped_teams).values("organization_id"),
            )
            .select_related("team")
            .first()
        )
        if race_winner:
            if not user_can_access_team(user, race_winner.team):
                return None, scoped_teams
            return ensure_team_in_token_scopes(access_token, scoped_teams, race_winner.team)
        raise ProjectIdCollisionError(project_id)

    return ensure_team_in_token_scopes(access_token, scoped_teams, new_team)
