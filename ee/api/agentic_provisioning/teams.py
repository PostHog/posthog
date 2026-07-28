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


def resolve_team_for_existing_user(user: User, requested_team_id: int | None = None) -> Team | None:
    """Pick a team for an existing user during email-based account linking.

    If requested_team_id is provided and the user has access, use it.
    Otherwise auto-select: single non-demo team → use it, only demo teams →
    create a new project, multiple teams → create a new project in the first org.
    """
    memberships = list(user.organization_memberships.select_related("organization").all())
    if not memberships:
        return None

    org_ids = [m.organization_id for m in memberships]

    if requested_team_id is not None:
        try:
            team = Team.objects.get(id=requested_team_id, is_demo=False)
        except Team.DoesNotExist:
            return None
        if team.organization_id not in org_ids:
            return None
        # Org membership alone is not access: a partner can name any team id in
        # the user's orgs, so a team the user is excluded from must not become
        # the scope of the minted code.
        if not user_can_access_team(user, team):
            return None
        return team

    non_demo_teams = [
        team
        for team in Team.objects.filter(organization_id__in=org_ids, is_demo=False)
        if user_can_access_team(user, team)
    ]

    if len(non_demo_teams) == 1:
        return non_demo_teams[0]

    organization = memberships[0].organization
    return Team.objects.create_with_data(initiating_user=user, organization=organization)


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
