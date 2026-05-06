from posthog.models import Team


def get_scoped_team_ids(team: Team) -> list[int]:
    if not team.can_query_across_organization_projects:
        return [team.id]

    return sorted(Team.objects.filter(organization_id=team.organization_id).values_list("id", flat=True))
