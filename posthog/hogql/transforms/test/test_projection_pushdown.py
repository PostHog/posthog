from posthog.test.base import BaseTest

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing
from posthog.hogql.transforms.projection_pushdown import pushdown_projections


class TestProjectionPushdown(BaseTest):
    maxDiff = None

    def _optimize(self, query_str: str):
        """Helper: parse, resolve, and optimize a query"""
        modifiers = HogQLQueryModifiers(optimizeProjections=False)  # Disable automatic optimization
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=modifiers)
        query = parse_select(query_str)
        query = prepare_ast_for_printing(query, context, dialect="hogql")
        optimized = pushdown_projections(query, context)
        return optimized

    def test_simple_pushdown(self):
        """SELECT event FROM (SELECT * FROM events)"""
        optimized = self._optimize("SELECT event FROM (SELECT * FROM events) AS sub")

        # Inner query should only select 'event'
        inner_query = optimized.select_from.table
        assert len(inner_query.select) == 1

        # The column might be aliased
        first_col = inner_query.select[0]
        if hasattr(first_col, "alias"):
            assert first_col.alias == "event"
        else:
            assert first_col.chain == ["event"]
        assert getattr(first_col, "from_asterisk", False)

    def _col_name(self, col):
        """Helper to get column name for debugging"""
        if hasattr(col, "alias"):
            return col.alias
        if hasattr(col, "chain") and col.chain:
            return col.chain[-1]
        return "?"

    def test_preserves_used_columns(self):
        """Columns in WHERE/GROUP BY also needed"""
        optimized = self._optimize("""
            SELECT event, count()
            FROM (SELECT * FROM events) AS sub
            WHERE distinct_id = 'test'
            GROUP BY timestamp
        """)

        inner_query = optimized.select_from.table
        column_names = {self._col_name(col) for col in inner_query.select}
        assert column_names >= {"event", "distinct_id", "timestamp"}

    def test_no_pushdown_without_asterisk(self):
        """Don't modify queries without asterisk"""
        optimized = self._optimize("SELECT event FROM (SELECT event, distinct_id FROM events) AS sub")

        inner_query = optimized.select_from.table
        assert len(inner_query.select) == 2

    def test_nested_pushdown(self):
        """Pushdown through multiple levels"""
        optimized = self._optimize("""
            SELECT event FROM (
                SELECT * FROM (
                    SELECT * FROM events
                ) AS inner
            ) AS outer
        """)

        # Both inner queries should only have 'event'
        # Check outer subquery
        outer_query = optimized.select_from.table
        assert len(outer_query.select) == 1
        assert self._col_name(outer_query.select[0]) == "event"

        # Check inner subquery
        inner_query = outer_query.select_from.table
        assert len(inner_query.select) == 1
        assert self._col_name(inner_query.select[0]) == "event"

    def test_preserves_explicit_columns(self):
        """Don't prune columns user explicitly wrote"""
        optimized = self._optimize("""
            SELECT event FROM (
                SELECT event, distinct_id, timestamp FROM events
            ) AS sub
        """)

        # Should keep all columns (none have from_asterisk=True)
        inner_query = optimized.select_from.table
        assert len(inner_query.select) == 3

    def test_prewhere_clause(self):
        """PREWHERE clause columns should be preserved"""
        optimized = self._optimize("""
            SELECT event
            FROM (SELECT * FROM events) AS sub
            PREWHERE distinct_id = 'test'
        """)

        # Should include both event and distinct_id
        inner_query = optimized.select_from.table
        column_names = {self._col_name(col) for col in inner_query.select}
        assert "event" in column_names
        assert "distinct_id" in column_names

    def test_order_by_clause(self):
        """ORDER BY clause columns should be preserved"""
        optimized = self._optimize("""
            SELECT event
            FROM (SELECT * FROM events) AS sub
            ORDER BY timestamp DESC
        """)

        # Should include both event and timestamp
        inner_query = optimized.select_from.table
        column_names = {self._col_name(col) for col in inner_query.select}
        assert "event" in column_names
        assert "timestamp" in column_names

    def test_join_constraint_columns(self):
        """Columns in JOIN conditions should be preserved"""
        optimized = self._optimize("""
            SELECT e.event, e.distinct_id
            FROM (SELECT * FROM events) AS e
            LEFT JOIN sessions ON sessions.id = e.`$session_id`
        """)

        # Should include event, distinct_id, AND $session_id (from JOIN)
        inner_query = optimized.select_from.table
        column_names = {self._col_name(col) for col in inner_query.select}
        assert "event" in column_names
        assert "distinct_id" in column_names
        assert "$session_id" in column_names

    def test_join_constraint_in_subquery(self):
        """Subquery JOIN constraints should preserve columns"""
        optimized = self._optimize("""
            SELECT * FROM (
                SELECT e.event, e.distinct_id, sessions.id
                FROM (SELECT * FROM events) AS e
                LEFT JOIN sessions ON sessions.id = e.`$session_id`
            )
        """)

        assert optimized.select_from is not None
        nested_query = optimized.select_from.table

        assert nested_query.select_from is not None
        inner_query = nested_query.select_from.table

        # Should include event, distinct_id, AND $session_id (from JOIN)
        column_names = {self._col_name(col) for col in inner_query.select}
        assert "event" in column_names
        assert "distinct_id" in column_names
        assert "$session_id" in column_names, f"Got columns: {column_names}"
