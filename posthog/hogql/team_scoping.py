from collections.abc import Iterable
from typing import Literal

from posthog.models import Team, User
from posthog.models.organization import OrganizationMembership
from posthog.rbac.user_access_control import UserAccessControlError

TeamsToQuery = Literal["all"] | Literal["self"] | list[int] | None


def _normalize_requested_team_ids(requested_team_ids: Iterable[int]) -> list[int]:
    normalized_ids: set[int] = set()
    for team_id in requested_team_ids:
        if isinstance(team_id, bool):
            raise UserAccessControlError("project", "admin")
        normalized_ids.add(int(team_id))

    if not normalized_ids:
        raise UserAccessControlError("project", "admin")

    return sorted(normalized_ids)


def _validate_cross_project_query_access(team: Team, user: User | None) -> None:
    if not team.can_query_across_organization_projects:
        raise UserAccessControlError("project", "admin", str(team.id))

    if user is None:
        raise UserAccessControlError("project", "admin", str(team.id))

    membership = OrganizationMembership.objects.filter(user=user, organization_id=team.organization_id).first()
    if membership is None or membership.level < OrganizationMembership.Level.ADMIN:
        raise UserAccessControlError("project", "admin", str(team.id))


def get_scoped_team_ids(team: Team, user: User | None, teams_to_query: TeamsToQuery) -> list[int]:
    if teams_to_query in (None, "self"):
        return [team.id]

    _validate_cross_project_query_access(team, user)

    org_team_ids = set(Team.objects.filter(organization_id=team.organization_id).values_list("id", flat=True))

    if teams_to_query == "all":
        return sorted(org_team_ids)

    requested_team_ids = _normalize_requested_team_ids(teams_to_query)
    unauthorized_team_ids = sorted(set(requested_team_ids) - org_team_ids)
    if unauthorized_team_ids:
        raise UserAccessControlError("project", "admin", str(team.id))

    return requested_team_ids
