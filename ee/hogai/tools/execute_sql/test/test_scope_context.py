import json

from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async

from ee.hogai.tools.execute_sql.scope_context import format_execute_sql_project_scope_context


class TestExecuteSQLScopeContext(BaseTest):
    async def test_formats_single_project_scope_context(self) -> None:
        context = await format_execute_sql_project_scope_context(self.team)

        self.assertIn("This project queries only the current project by default.", context)
        self.assertIn(f"The current team is {json.dumps(self.team.name)}", context)
        self.assertIn(f"`team_id = {self.team.id}`", context)
        self.assertIn("other project data is not in scope", context)

    async def test_formats_organization_scope_context(self) -> None:
        self.team.can_query_across_organization_projects = True
        await sync_to_async(self.team.save)()

        context = await format_execute_sql_project_scope_context(self.team)

        self.assertIn("This project queries across all projects in the organization by default.", context)
        self.assertIn("Only use `team_id` for per-project filtering or breakdowns.", context)
        self.assertIn("If you need project IDs or names, query `system.teams`.", context)
