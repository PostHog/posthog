import json

from django.test import SimpleTestCase

from asgiref.sync import async_to_sync

from posthog.models import Team

from ee.hogai.tools.execute_sql.scope_context import format_execute_sql_project_scope_context


class TestExecuteSQLScopeContext(SimpleTestCase):
    def test_formats_single_project_scope_context(self) -> None:
        team = Team(id=123, name='Main "Team"', can_query_across_organization_projects=False)

        context = async_to_sync(format_execute_sql_project_scope_context)(team)

        self.assertIn("This project queries only the current project by default.", context)
        self.assertIn(f"The current team is {json.dumps(team.name)}", context)
        self.assertIn(f"`team_id = {team.id}`", context)
        self.assertIn("other project data is not in scope", context)

    def test_formats_organization_scope_context(self) -> None:
        team = Team(id=123, name="Main Team", can_query_across_organization_projects=True)

        context = async_to_sync(format_execute_sql_project_scope_context)(team)

        self.assertIn("This project queries across all projects in the organization by default.", context)
        self.assertIn("Only use `team_id` for per-project filtering or breakdowns.", context)
        self.assertIn("If you need project IDs or names, query `system.teams`.", context)
