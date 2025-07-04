from typing import cast

from posthog.hogql import ast
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.schema import EventsQuery
from posthog.test.base import APIBaseTest


class TestRecentEventsTable(APIBaseTest):
    def test_events_query_uses_regular_events_table_by_default(self):
        query = EventsQuery(select=["*"], after="-24h")
        runner = EventsQueryRunner(query=query, team=self.team)

        # Generate the AST query
        ast_query = runner.to_query()

        # Check that it uses the regular events table
        assert ast_query.select_from is not None
        assert ast_query.select_from.table is not None
        field = cast(ast.Field, ast_query.select_from.table)
        table_name = field.chain[0]
        self.assertEqual(table_name, "events")

    def test_events_query_uses_recent_events_table_when_flag_is_true(self):
        query = EventsQuery(select=["*"], after="-24h", useRecentEventsTable=True)
        runner = EventsQueryRunner(query=query, team=self.team)

        # Generate the AST query
        ast_query = runner.to_query()

        # Check that it uses the recent_events table
        assert ast_query.select_from is not None
        assert ast_query.select_from.table is not None
        field = cast(ast.Field, ast_query.select_from.table)
        table_name = field.chain[0]
        self.assertEqual(table_name, "recent_events")

    def test_events_query_uses_regular_events_table_when_flag_is_false(self):
        query = EventsQuery(select=["*"], after="-24h", useRecentEventsTable=False)
        runner = EventsQueryRunner(query=query, team=self.team)

        # Generate the AST query
        ast_query = runner.to_query()

        # Check that it uses the regular events table
        assert ast_query.select_from is not None
        assert ast_query.select_from.table is not None
        field = cast(ast.Field, ast_query.select_from.table)
        table_name = field.chain[0]
        self.assertEqual(table_name, "events")

    def test_presorted_table_respects_recent_events_flag(self):
        # Test with regular events table (default)
        query_regular = EventsQuery(
            select=["*"], after="-24h", orderBy=["timestamp DESC"], modifiers={"usePresortedEventsTable": True}
        )
        runner_regular = EventsQueryRunner(query=query_regular, team=self.team)
        ast_regular = runner_regular.to_query()

        # Test with recent events table
        query_recent = EventsQuery(
            select=["*"],
            after="-24h",
            orderBy=["timestamp DESC"],
            useRecentEventsTable=True,
            modifiers={"usePresortedEventsTable": True},
        )
        runner_recent = EventsQueryRunner(query=query_recent, team=self.team)
        ast_recent = runner_recent.to_query()

        # Both should use their respective tables
        assert ast_regular.select_from is not None
        assert ast_regular.select_from.table is not None
        regular_field = cast(ast.Field, ast_regular.select_from.table)
        regular_table = regular_field.chain[0]

        assert ast_recent.select_from is not None
        assert ast_recent.select_from.table is not None
        recent_field = cast(ast.Field, ast_recent.select_from.table)
        recent_table = recent_field.chain[0]

        self.assertEqual(regular_table, "events")
        self.assertEqual(recent_table, "recent_events")
