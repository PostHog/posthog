from typing import cast
from freezegun import freeze_time

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

    def test_auto_fallback_to_events_table_when_date_range_outside_7_days(self):
        """Test that the query auto-falls back to events table when date range is outside last 7 days"""
        with freeze_time("2024-01-15T12:00:00Z"):
            # Test with date range 10 days ago (outside 7 days) - should fallback to events table
            query_old = EventsQuery(
                select=["*"],
                after="-10d",  # 10 days ago
                useRecentEventsTable=True,
            )
            runner_old = EventsQueryRunner(query=query_old, team=self.team)
            ast_old = runner_old.to_query()

            # Should use events table despite useRecentEventsTable=True
            assert ast_old.select_from is not None
            assert ast_old.select_from.table is not None
            field_old = cast(ast.Field, ast_old.select_from.table)
            table_name_old = field_old.chain[0]
            self.assertEqual(table_name_old, "events")

    def test_uses_recent_events_table_when_date_range_within_7_days(self):
        """Test that recent_events table is used when date range is within last 7 days"""
        with freeze_time("2024-01-15T12:00:00Z"):
            # Test with date range 5 days ago (within 7 days) - should use recent_events table
            query_recent = EventsQuery(
                select=["*"],
                after="-5d",  # 5 days ago
                useRecentEventsTable=True,
            )
            runner_recent = EventsQueryRunner(query=query_recent, team=self.team)
            ast_recent = runner_recent.to_query()

            # Should use recent_events table
            assert ast_recent.select_from is not None
            assert ast_recent.select_from.table is not None
            field_recent = cast(ast.Field, ast_recent.select_from.table)
            table_name_recent = field_recent.chain[0]
            self.assertEqual(table_name_recent, "recent_events")

    def test_auto_fallback_with_specific_date_outside_7_days(self):
        """Test fallback behavior with specific date that's outside 7 days"""
        with freeze_time("2024-01-15T12:00:00Z"):
            # Test with specific date 10 days ago
            query_specific = EventsQuery(
                select=["*"],
                after="2024-01-05T00:00:00Z",  # 10 days ago
                useRecentEventsTable=True,
            )
            runner_specific = EventsQueryRunner(query=query_specific, team=self.team)
            ast_specific = runner_specific.to_query()

            # Should use events table
            assert ast_specific.select_from is not None
            assert ast_specific.select_from.table is not None
            field_specific = cast(ast.Field, ast_specific.select_from.table)
            table_name_specific = field_specific.chain[0]
            self.assertEqual(table_name_specific, "events")

    def test_partition_pruning_with_inserted_at_filter(self):
        """Test that inserted_at filter is added for partition pruning when using recent_events table"""
        with freeze_time("2024-01-15T12:00:00Z"):
            # Test with recent date range - should add inserted_at filter
            query_recent = EventsQuery(
                select=["*"],
                after="-2d",  # 2 days ago
                useRecentEventsTable=True,
            )
            runner_recent = EventsQueryRunner(query=query_recent, team=self.team)
            ast_recent = runner_recent.to_query()

            # Should use recent_events table
            assert ast_recent.select_from is not None
            assert ast_recent.select_from.table is not None
            field_recent = cast(ast.Field, ast_recent.select_from.table)
            table_name_recent = field_recent.chain[0]
            self.assertEqual(table_name_recent, "recent_events")

            # Check that where clause includes inserted_at filter
            assert ast_recent.where is not None
            where_clause = ast_recent.where

            # The inserted_at filter should be present in the where clause
            # We need to check the AST structure for a comparison with inserted_at
            self._assert_has_inserted_at_filter(where_clause)

    def test_no_inserted_at_filter_when_using_events_table(self):
        """Test that inserted_at filter is not added when using events table"""
        with freeze_time("2024-01-15T12:00:00Z"):
            # Test with old date range - should use events table and no inserted_at filter
            query_old = EventsQuery(
                select=["*"],
                after="-10d",  # 10 days ago
                useRecentEventsTable=True,
            )
            runner_old = EventsQueryRunner(query=query_old, team=self.team)
            ast_old = runner_old.to_query()

            # Should use events table
            assert ast_old.select_from is not None
            assert ast_old.select_from.table is not None
            field_old = cast(ast.Field, ast_old.select_from.table)
            table_name_old = field_old.chain[0]
            self.assertEqual(table_name_old, "events")

            # Should not have inserted_at filter
            if ast_old.where is not None:
                self._assert_no_inserted_at_filter(ast_old.where)

    def test_fallback_with_after_all(self):
        """Test that 'all' value for after parameter doesn't cause fallback"""
        query_all = EventsQuery(select=["*"], after="all", useRecentEventsTable=True)
        runner_all = EventsQueryRunner(query=query_all, team=self.team)
        ast_all = runner_all.to_query()

        # Should use recent_events table when after="all"
        assert ast_all.select_from is not None
        assert ast_all.select_from.table is not None
        field_all = cast(ast.Field, ast_all.select_from.table)
        table_name_all = field_all.chain[0]
        self.assertEqual(table_name_all, "recent_events")

    def _assert_has_inserted_at_filter(self, where_clause: ast.Expr):
        """Helper method to check if inserted_at filter is present in where clause"""
        if isinstance(where_clause, ast.And):
            # Check all expressions in the AND clause
            for expr in where_clause.exprs:
                if self._is_inserted_at_filter(expr):
                    return
            self.fail("inserted_at filter not found in where clause")
        elif self._is_inserted_at_filter(where_clause):
            return
        else:
            self.fail("inserted_at filter not found in where clause")

    def _assert_no_inserted_at_filter(self, where_clause: ast.Expr):
        """Helper method to check that inserted_at filter is not present in where clause"""
        if isinstance(where_clause, ast.And):
            # Check all expressions in the AND clause
            for expr in where_clause.exprs:
                if self._is_inserted_at_filter(expr):
                    self.fail("inserted_at filter should not be present")
        elif self._is_inserted_at_filter(where_clause):
            self.fail("inserted_at filter should not be present")

    def _is_inserted_at_filter(self, expr: ast.Expr) -> bool:
        """Helper method to check if an expression is an inserted_at filter"""
        if isinstance(expr, ast.CompareOperation):
            if isinstance(expr.left, ast.Field) and len(expr.left.chain) == 1:
                return expr.left.chain[0] == "inserted_at"
        return False
