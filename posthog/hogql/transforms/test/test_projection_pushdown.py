import pytest
from posthog.test.base import BaseTest

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing
from posthog.hogql.transforms.projection_pushdown import pushdown_projections


class TestProjectionPushdown(BaseTest):
    maxDiff = None
    snapshot: object

    def _optimize(self, query_str: str):
        """Helper: parse, resolve, and optimize a query"""
        modifiers = HogQLQueryModifiers(optimizeProjections=False)  # Disable automatic optimization
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=modifiers)
        query = parse_select(query_str)
        prepared = prepare_ast_for_printing(query, context, dialect="hogql")
        assert prepared is not None
        optimized = pushdown_projections(prepared, context)
        return optimized

    @pytest.mark.usefixtures("unittest_snapshot")
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
        assert first_col.from_asterisk if isinstance(first_col, ast.Field) else first_col.expr.from_asterisk

        assert optimized.to_hogql() == self.snapshot

    def _col_name(self, col):
        """Helper to get column name for debugging"""
        if hasattr(col, "alias"):
            return col.alias
        if hasattr(col, "chain") and col.chain:
            return col.chain[-1]
        return "?"

    @pytest.mark.usefixtures("unittest_snapshot")
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

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_no_pushdown_without_asterisk(self):
        """Don't modify queries without asterisk"""
        optimized = self._optimize("SELECT event FROM (SELECT event, distinct_id FROM events) AS sub")

        inner_query = optimized.select_from.table
        assert len(inner_query.select) == 2

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
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

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
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

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
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

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
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

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
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

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
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

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_multiple_joins_with_mixed_columns(self):
        """Complex query with multiple JOINs and mixed SELECT/WHERE demands"""
        optimized = self._optimize("""
            SELECT e.event, e2.event as event2
            FROM (SELECT * FROM events) AS e
            LEFT JOIN (SELECT * FROM events) AS e2 ON e2.distinct_id = e.distinct_id
            WHERE e.timestamp > '2024-01-01'
            ORDER BY e.created_at
        """)

        # First events subquery should have: event, distinct_id (JOIN), timestamp (WHERE), created_at (ORDER BY)
        events_query = optimized.select_from.table
        events_cols = {self._col_name(col) for col in events_query.select}
        assert events_cols >= {"event", "distinct_id", "timestamp", "created_at"}

        # Second events subquery should have: event (SELECT) and distinct_id (JOIN constraint)
        events2_query = optimized.select_from.next_join.table
        events2_cols = {self._col_name(col) for col in events2_query.select}
        assert events2_cols >= {"event", "distinct_id"}

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_deeply_nested_with_multiple_demands(self):
        """4 levels deep with demands at each level"""
        optimized = self._optimize("""
            SELECT event FROM (
                SELECT event, distinct_id FROM (
                    SELECT event, distinct_id, timestamp FROM (
                        SELECT * FROM events
                    ) AS l3
                    WHERE timestamp > '2024-01-01'
                ) AS l2
                WHERE distinct_id = 'user1'
            ) AS l1
        """)

        # Level 1: event, distinct_id
        l1 = optimized.select_from.table
        l1_cols = {self._col_name(col) for col in l1.select}
        assert l1_cols == {"event", "distinct_id"}

        # Level 2: event, distinct_id, timestamp
        l2 = l1.select_from.table
        l2_cols = {self._col_name(col) for col in l2.select}
        assert l2_cols == {"event", "distinct_id", "timestamp"}

        # Level 3: Only event, distinct_id, timestamp (pruned from asterisk)
        l3 = l2.select_from.table
        l3_cols = {self._col_name(col) for col in l3.select}
        assert l3_cols == {"event", "distinct_id", "timestamp"}

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_mixed_asterisk_and_explicit_columns(self):
        """Query with both SELECT *, col1, col2 pattern"""
        optimized = self._optimize("""
            SELECT event FROM (
                SELECT distinct_id, *, timestamp FROM events
            ) AS sub
        """)

        # Should keep distinct_id and timestamp (explicit) plus event (demanded from asterisk)
        inner_query = optimized.select_from.table
        column_names = {self._col_name(col) for col in inner_query.select}
        assert "event" in column_names
        assert "distinct_id" in column_names
        assert "timestamp" in column_names

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_group_by_and_having_demands(self):
        """Ensure GROUP BY and HAVING columns are preserved"""
        optimized = self._optimize("""
            SELECT event, count() as cnt
            FROM (SELECT * FROM events) AS sub
            GROUP BY event, distinct_id
            HAVING count() > 10 AND timestamp > '2024-01-01'
        """)

        # Should include event (SELECT + GROUP BY), distinct_id (GROUP BY), timestamp (HAVING)
        inner_query = optimized.select_from.table
        column_names = {self._col_name(col) for col in inner_query.select}
        assert column_names >= {"event", "distinct_id", "timestamp"}

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_subquery_in_join_with_demands(self):
        """Nested subqueries in both sides of JOIN"""
        optimized = self._optimize("""
            SELECT e1.event, e2.timestamp
            FROM (
                SELECT * FROM (SELECT * FROM events) AS inner_e1
            ) AS e1
            LEFT JOIN (
                SELECT * FROM (SELECT * FROM events) AS inner_e2
            ) AS e2 ON e2.distinct_id = e1.distinct_id
            WHERE e1.properties != '{}'
        """)

        # Outer e1 subquery
        outer_e1 = optimized.select_from.table
        outer_e1_cols = {self._col_name(col) for col in outer_e1.select}
        assert outer_e1_cols >= {"event", "distinct_id", "properties"}

        # Inner e1 subquery should have same demands propagated
        inner_e1 = outer_e1.select_from.table
        inner_e1_cols = {self._col_name(col) for col in inner_e1.select}
        assert inner_e1_cols >= {"event", "distinct_id", "properties"}

        # Outer e2 subquery
        outer_e2 = optimized.select_from.next_join.table
        outer_e2_cols = {self._col_name(col) for col in outer_e2.select}
        assert outer_e2_cols >= {"timestamp", "distinct_id"}

        # Inner e2 subquery
        inner_e2 = outer_e2.select_from.table
        inner_e2_cols = {self._col_name(col) for col in inner_e2.select}
        assert inner_e2_cols >= {"timestamp", "distinct_id"}

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_union_all_without_alias(self):
        """UNION ALL without subquery alias should still be pruned"""
        optimized = self._optimize("""
            SELECT event FROM (
                SELECT * FROM events UNION ALL SELECT * FROM events
            )
        """)

        # The UNION subquery should be a SelectSetQuery
        union_query = optimized.select_from.table
        assert isinstance(union_query, ast.SelectSetQuery)

        # Both branches should only have 'event' column
        first_branch = union_query.initial_select_query
        assert isinstance(first_branch, ast.SelectQuery)
        first_cols = {self._col_name(col) for col in first_branch.select}
        assert first_cols == {"event"}, f"Expected only 'event' but got {first_cols}"

        second_branch = union_query.subsequent_select_queries[0].select_query
        assert isinstance(second_branch, ast.SelectQuery)
        second_cols = {self._col_name(col) for col in second_branch.select}
        assert second_cols == {"event"}, f"Expected only 'event' but got {second_cols}"

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_union_all_with_asterisk(self):
        """UNION ALL branches with asterisk should be pruned uniformly"""
        optimized = self._optimize("""
            SELECT event, distinct_id FROM (
                SELECT * FROM events WHERE event = 'click'
                UNION ALL
                SELECT * FROM events WHERE event = 'pageview'
            ) AS sub
        """)

        # The UNION subquery should be a SelectSetQuery
        union_query = optimized.select_from.table
        assert isinstance(union_query, ast.SelectSetQuery)

        # Both branches should have the same columns (event, distinct_id)
        first_branch = union_query.initial_select_query
        assert isinstance(first_branch, ast.SelectQuery)
        first_cols = {self._col_name(col) for col in first_branch.select}
        assert first_cols == {"event", "distinct_id"}

        second_branch = union_query.subsequent_select_queries[0].select_query
        assert isinstance(second_branch, ast.SelectQuery)
        second_cols = {self._col_name(col) for col in second_branch.select}
        assert second_cols == {"event", "distinct_id"}

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_union_all_multiple_branches(self):
        """UNION ALL with 3+ branches should all be pruned uniformly"""
        optimized = self._optimize("""
            SELECT event FROM (
                SELECT * FROM events WHERE event = 'click'
                UNION ALL
                SELECT * FROM events WHERE event = 'pageview'
                UNION ALL
                SELECT * FROM events WHERE event = 'submit'
            ) AS sub
        """)

        union_query = optimized.select_from.table
        assert isinstance(union_query, ast.SelectSetQuery)

        # All three branches should only have 'event' column
        all_branches = [union_query.initial_select_query] + [
            sn.select_query for sn in union_query.subsequent_select_queries
        ]

        for branch in all_branches:
            assert isinstance(branch, ast.SelectQuery)
            cols = {self._col_name(col) for col in branch.select}
            assert cols == {"event"}, f"Expected only 'event' but got {cols}"

        assert optimized.to_hogql() == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_cte_with_asterisk_pushdown(self):
        """CTEs with asterisk should have projection pushdown applied after CTE inlining"""
        optimized = self._optimize("""
            WITH events_cte AS (
                SELECT * FROM events
            )
            SELECT event, distinct_id FROM events_cte
            WHERE timestamp > '2024-01-01'
        """)

        # After CTE inlining, the CTE becomes a subquery
        # The subquery should only have the columns we actually need
        assert optimized.select_from is not None
        subquery = optimized.select_from.table
        column_names = {self._col_name(col) for col in subquery.select}
        assert column_names >= {"event", "distinct_id", "timestamp"}
        # Verify columns have from_asterisk marker
        assert any(
            col.from_asterisk if isinstance(col, ast.Field) else col.expr.from_asterisk for col in subquery.select
        )

        assert optimized.to_hogql() == self.snapshot
