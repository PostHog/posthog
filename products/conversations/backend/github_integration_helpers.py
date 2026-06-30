from __future__ import annotations

from uuid import UUID

from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

_GITHUB_REPO_LIST_LIMIT = 200


def user_is_conversations_admin(user: User, organization_id: UUID) -> bool:
    try:
        membership = OrganizationMembership.objects.get(user=user, organization_id=organization_id)
    except OrganizationMembership.DoesNotExist:
        return False
    return membership.level >= OrganizationMembership.Level.ADMIN


def resolve_team_github_integration(team: Team) -> Integration | None:
    settings_dict = team.conversations_settings or {}
    integration_id = settings_dict.get("github_integration_id")
    if integration_id:
        integration = Integration.objects.filter(id=integration_id, team=team, kind="github").first()
        if integration is not None:
            return integration
    return Integration.objects.filter(team=team, kind="github").first()


def team_github_integration_present(team: Team) -> bool:
    return resolve_team_github_integration(team) is not None


def team_github_repo_accessible(team: Team, repo: str, *, integration: Integration | None = None) -> bool:
    integration = integration or resolve_team_github_integration(team)
    if integration is None:
        return False
    github = GitHubIntegration(integration)
    repos, _has_more = github.list_cached_repositories(limit=_GITHUB_REPO_LIST_LIMIT)
    accessible = {full_name for r in repos if (full_name := r.get("full_name"))}
    return repo in accessible
