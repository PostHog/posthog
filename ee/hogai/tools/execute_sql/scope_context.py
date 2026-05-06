from asgiref.sync import sync_to_async

from posthog.models import Team


@sync_to_async
def format_execute_sql_project_scope_context(team: Team) -> str:
    org_teams = list(Team.objects.filter(organization_id=team.organization_id).order_by("id").values_list("id", "name"))
    teams_listing = "\n".join(f"- team_id={team_id}: {team_name}" for team_id, team_name in org_teams)

    if team.can_query_across_organization_projects:
        return (
            f"The current project is {team.name} (team_id={team.id}). Cross-project querying is enabled for this "
            "project, so queries automatically run across all projects in this organization by default.\n"
            "Do NOT add a `WHERE team_id = ...` filter just to make a query org-wide.\n"
            "Use `team_id` only when the user explicitly asks for a per-project/app filter, grouping, "
            "comparison, ranking, or breakdown.\n"
            "Projects currently in scope:\n"
            f"{teams_listing}"
        )

    return (
        f"The current project is {team.name} (team_id={team.id}). Cross-project querying is disabled for this "
        "project, so queries only see this project by default.\n"
        "Use `team_id` only when the user explicitly asks for a per-project/app breakdown or when you need to "
        "label grouped results.\n"
        "Projects in this organization:\n"
        f"{teams_listing}"
    )
