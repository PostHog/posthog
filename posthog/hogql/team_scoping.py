from typing import TYPE_CHECKING

from posthog.models import Team
from posthog.user_permissions import UserPermissions

if TYPE_CHECKING:
    from posthog.models import User


def get_scoped_team_ids(team: Team, user: "User | None" = None) -> list[int]:
    if not team.can_query_across_organization_projects:
        return sorted(Team.objects.filter(project_id=team.project_id).values_list("id", flat=True))

    if user is None:
        return sorted(Team.objects.filter(project_id=team.project_id).values_list("id", flat=True))

    visible_team_ids = UserPermissions(user).team_ids_visible_for_user
    return sorted(
        Team.objects.filter(organization_id=team.organization_id, id__in=visible_team_ids).values_list("id", flat=True)
    )
