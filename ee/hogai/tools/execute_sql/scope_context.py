from asgiref.sync import sync_to_async

from posthog.models import Team


@sync_to_async
def format_execute_sql_project_scope_context(team: Team) -> str:
    if not team.can_query_across_organization_projects:
        return ""

    return (
        "This project queries across all projects in the organization by default. "
        "Only use `team_id` for per-project filtering or breakdowns. "
        "If you need project IDs or names, query `system.teams`."
    )
