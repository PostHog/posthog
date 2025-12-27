from datetime import datetime
from uuid import uuid4

from posthog.test.base import BaseTest, QueryMatchingTest, _create_event

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.sql import SHARDED_PREAGGREGATION_RESULTS_TABLE

from products.analytics_platform.backend.lazy_preaggregation.lazy_preaggregation_transformer import (
    PREAGGREGATED_DAILY_UNIQUE_PERSONS_PAGEVIEWS_TABLE_NAME,
    Transformer,
    _extract_timestamp_range,
    _flatten_and,
    _is_daily_unique_persons_pageviews_query,
    _is_pageview_filter,
    _is_person_id_field,
    _is_timestamp_field,
    _is_to_start_of_day_timestamp,
    _is_uniq_exact_persons_call,
)


class TestPatternDetection(BaseTest):
    """Tests for individual pattern detection functions."""

    def test_is_person_id_field(self):
        from posthog.hogql import ast

        # Positive cases
        assert _is_person_id_field(ast.Field(chain=["person_id"]))
        assert _is_person_id_field(ast.Field(chain=["person", "id"]))
        assert _is_person_id_field(ast.Field(chain=["events", "person_id"]))
        assert _is_person_id_field(ast.Field(chain=["events", "person", "id"]))
        assert _is_person_id_field(ast.Field(chain=["e", "person_id"]))
        assert _is_person_id_field(ast.Field(chain=["e", "person", "id"]))

        # Negative cases
        assert not _is_person_id_field(ast.Field(chain=["id"]))
        assert not _is_person_id_field(ast.Field(chain=["user_id"]))
        assert not _is_person_id_field(ast.Field(chain=["event"]))

    def test_is_timestamp_field(self):
        from posthog.hogql import ast

        context = HogQLContext(team_id=self.team.pk, team=self.team)

        # Positive cases
        assert _is_timestamp_field(ast.Field(chain=["timestamp"]), context)
        assert _is_timestamp_field(ast.Field(chain=["events", "timestamp"]), context)
        assert _is_timestamp_field(ast.Field(chain=["e", "timestamp"]), context)

        # Negative cases
        assert not _is_timestamp_field(ast.Field(chain=["time"]), context)
        assert not _is_timestamp_field(ast.Field(chain=["created_at"]), context)
        assert not _is_timestamp_field(ast.Constant(value="timestamp"), context)

    def test_is_pageview_filter(self):
        from posthog.hogql import ast
        from posthog.hogql.ast import CompareOperationOp

        # Positive cases: event = '$pageview'
        expr1 = ast.CompareOperation(
            left=ast.Field(chain=["event"]), right=ast.Constant(value="$pageview"), op=CompareOperationOp.Eq
        )
        assert _is_pageview_filter(expr1)

        # Reversed: '$pageview' = event
        expr2 = ast.CompareOperation(
            left=ast.Constant(value="$pageview"), right=ast.Field(chain=["event"]), op=CompareOperationOp.Eq
        )
        assert _is_pageview_filter(expr2)

        # With table alias: events.event = '$pageview'
        expr3 = ast.CompareOperation(
            left=ast.Field(chain=["events", "event"]), right=ast.Constant(value="$pageview"), op=CompareOperationOp.Eq
        )
        assert _is_pageview_filter(expr3)

        # Negative cases
        expr4 = ast.CompareOperation(
            left=ast.Field(chain=["event"]), right=ast.Constant(value="$pageclick"), op=CompareOperationOp.Eq
        )
        assert not _is_pageview_filter(expr4)

    def test_is_uniq_exact_persons_call(self):
        from posthog.hogql import ast

        # Positive cases: uniqExact(person_id)
        expr1 = ast.Call(name="uniqExact", args=[ast.Field(chain=["person_id"])])
        assert _is_uniq_exact_persons_call(expr1)

        # count(DISTINCT person_id)
        expr2 = ast.Call(name="count", args=[ast.Field(chain=["person_id"])], distinct=True)
        assert _is_uniq_exact_persons_call(expr2)

        # uniqExact(events.person_id)
        expr3 = ast.Call(name="uniqExact", args=[ast.Field(chain=["events", "person_id"])])
        assert _is_uniq_exact_persons_call(expr3)

        # uniqExact(person.id)
        expr4 = ast.Call(name="uniqExact", args=[ast.Field(chain=["person", "id"])])
        assert _is_uniq_exact_persons_call(expr4)

        # Negative cases: count(*)
        expr5 = ast.Call(name="count", args=[])
        assert not _is_uniq_exact_persons_call(expr5)

        # uniq(person_id) - not uniqExact
        expr6 = ast.Call(name="uniq", args=[ast.Field(chain=["person_id"])])
        assert not _is_uniq_exact_persons_call(expr6)

        # uniqExact(id) - wrong field
        expr7 = ast.Call(name="uniqExact", args=[ast.Field(chain=["id"])])
        assert not _is_uniq_exact_persons_call(expr7)

    def test_is_to_start_of_day_timestamp(self):
        from posthog.hogql import ast

        context = HogQLContext(team_id=self.team.pk, team=self.team)

        # Positive cases: toStartOfDay(timestamp)
        expr1 = ast.Call(name="toStartOfDay", args=[ast.Field(chain=["timestamp"])])
        assert _is_to_start_of_day_timestamp(expr1, context)

        # toStartOfInterval(timestamp, toIntervalDay(1))
        expr2 = ast.Call(
            name="toStartOfInterval",
            args=[ast.Field(chain=["timestamp"]), ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)])],
        )
        assert _is_to_start_of_day_timestamp(expr2, context)

        # With table alias: toStartOfDay(events.timestamp)
        expr3 = ast.Call(name="toStartOfDay", args=[ast.Field(chain=["events", "timestamp"])])
        assert _is_to_start_of_day_timestamp(expr3, context)

        # Negative cases: toStartOfHour(timestamp)
        expr4 = ast.Call(name="toStartOfHour", args=[ast.Field(chain=["timestamp"])])
        assert not _is_to_start_of_day_timestamp(expr4, context)

        # toStartOfDay(created_at) - wrong field
        expr5 = ast.Call(name="toStartOfDay", args=[ast.Field(chain=["created_at"])])
        assert not _is_to_start_of_day_timestamp(expr5, context)

    def test_extract_timestamp_range(self):
        from posthog.hogql import ast
        from posthog.hogql.ast import CompareOperationOp

        context = HogQLContext(team_id=self.team.pk, team=self.team)

        # Test case: timestamp >= '2024-01-01' AND timestamp < '2024-02-01'
        where_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value="2024-01-01 00:00:00"),
                op=CompareOperationOp.GtEq,
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value="2024-02-01 00:00:00"),
                op=CompareOperationOp.Lt,
            ),
        ]

        result = _extract_timestamp_range(where_exprs, context)
        assert result is not None
        start_dt, end_dt = result
        assert start_dt == datetime(2024, 1, 1, 0, 0, 0)
        assert end_dt == datetime(2024, 2, 1, 0, 0, 0)

    def test_flatten_and(self):
        from posthog.hogql import ast

        # Simple case: already flat
        expr1 = ast.Constant(value=1)
        assert _flatten_and(expr1) == [expr1]

        # AND with two expressions
        expr2 = ast.And(exprs=[ast.Constant(value=1), ast.Constant(value=2)])
        assert len(_flatten_and(expr2)) == 2

        # Nested AND
        expr3 = ast.And(exprs=[ast.Constant(value=1), ast.And(exprs=[ast.Constant(value=2), ast.Constant(value=3)])])
        assert len(_flatten_and(expr3)) == 3

        # None
        assert _flatten_and(None) == []


class TestQueryPatternDetection(BaseTest):
    """Tests for the main query pattern detection function."""

    def _parse_select(self, query: str) -> ast.SelectQuery:
        node = parse_select(query)
        assert isinstance(node, ast.SelectQuery)
        return node

    def test_basic_matching_query(self):
        query = """
            SELECT uniqExact(person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp)
        """
        node = self._parse_select(query)
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        assert _is_daily_unique_persons_pageviews_query(node, context)

    def test_count_distinct_variant(self):
        query = """
            SELECT count(DISTINCT person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp)
        """
        node = self._parse_select(query)
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        assert _is_daily_unique_persons_pageviews_query(node, context)

    def test_with_alias(self):
        query = """
            SELECT uniqExact(person_id) AS unique_persons
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp) AS day
        """
        node = self._parse_select(query)
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        assert _is_daily_unique_persons_pageviews_query(node, context)

    def test_with_toStartOfDay_in_where_clause(self):
        """Test query with toStartOfDay(timestamp) in WHERE instead of raw timestamp."""
        query = """
            SELECT uniqExact(person_id)
            FROM events
            WHERE event = '$pageview'
              AND toStartOfDay(timestamp) > '2025-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp)
        """
        node = self._parse_select(query)
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        assert _is_daily_unique_persons_pageviews_query(node, context)

    def test_with_single_bound_date_range_not_supported(self):
        """Test query with only a start date (no end date)."""
        query = """
            SELECT uniqExact(person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
            GROUP BY toStartOfDay(timestamp)
        """
        node = self._parse_select(query)
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        # Should match and infer end date
        assert not _is_daily_unique_persons_pageviews_query(node, context)

    def test_with_single_breakdown(self):
        """Test query with one breakdown dimension."""
        query = """
            SELECT uniqExact(person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp), properties.$browser
        """
        node = self._parse_select(query)
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        assert _is_daily_unique_persons_pageviews_query(node, context)

    def test_with_multiple_breakdowns(self):
        """Test query with multiple breakdown dimensions."""
        query = """
            SELECT uniqExact(person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp), properties.$browser, properties.$os
        """
        node = self._parse_select(query)
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        assert _is_daily_unique_persons_pageviews_query(node, context)

    @parameterized.expand(
        [
            (
                "wrong_event",
                "SELECT uniqExact(person_id) FROM events WHERE event = 'other' AND timestamp >= '2024-01-01' AND timestamp < '2024-02-01' GROUP BY toStartOfDay(timestamp)",
            ),
            (
                "no_event_filter",
                "SELECT uniqExact(person_id) FROM events WHERE timestamp >= '2024-01-01' AND timestamp < '2024-02-01' GROUP BY toStartOfDay(timestamp)",
            ),
            (
                "wrong_aggregation",
                "SELECT count(*) FROM events WHERE event = '$pageview' AND timestamp >= '2024-01-01' AND timestamp < '2024-02-01' GROUP BY toStartOfDay(timestamp)",
            ),
            (
                "no_timestamp_range",
                "SELECT uniqExact(person_id) FROM events WHERE event = '$pageview' GROUP BY toStartOfDay(timestamp)",
            ),
            (
                "wrong_group_by",
                "SELECT uniqExact(person_id) FROM events WHERE event = '$pageview' AND timestamp >= '2024-01-01' AND timestamp < '2024-02-01' GROUP BY toStartOfHour(timestamp)",
            ),
            (
                "multiple_select",
                "SELECT uniqExact(person_id), count(*) FROM events WHERE event = '$pageview' AND timestamp >= '2024-01-01' AND timestamp < '2024-02-01' GROUP BY toStartOfDay(timestamp)",
            ),
            (
                "with_having",
                "SELECT uniqExact(person_id) FROM events WHERE event = '$pageview' AND timestamp >= '2024-01-01' AND timestamp < '2024-02-01' GROUP BY toStartOfDay(timestamp) HAVING uniqExact(person_id) > 10",
            ),
            (
                "with_distinct",
                "SELECT DISTINCT uniqExact(person_id) FROM events WHERE event = '$pageview' AND timestamp >= '2024-01-01' AND timestamp < '2024-02-01' GROUP BY toStartOfDay(timestamp)",
            ),
            (
                "from_sessions",
                "SELECT uniqExact(person_id) FROM sessions WHERE event = '$pageview' AND timestamp >= '2024-01-01' AND timestamp < '2024-02-01' GROUP BY toStartOfDay(timestamp)",
            ),
            (
                "with_join",
                "SELECT uniqExact(e.person_id) FROM events e JOIN sessions s ON e.session_id = s.id WHERE e.event = '$pageview' AND e.timestamp >= '2024-01-01' AND e.timestamp < '2024-02-01' GROUP BY toStartOfDay(e.timestamp)",
            ),
            (
                "breakdown_first_without_toStartOfDay",
                "SELECT uniqExact(person_id) FROM events WHERE event = '$pageview' AND timestamp >= '2024-01-01' AND timestamp < '2024-02-01' GROUP BY properties.$browser, toStartOfDay(timestamp)",
            ),
        ]
    )
    def test_non_matching_queries(self, name, query):
        node = self._parse_select(query)
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        assert not _is_daily_unique_persons_pageviews_query(node, context), f"Query should not match: {name}"


class TestQueryTransformation(BaseTest, QueryMatchingTest):
    """Tests for the query transformation logic."""

    replace_all_numbers = True

    def _parse_and_transform(self, query: str) -> str:
        node = parse_select(query)
        assert isinstance(node, ast.SelectQuery)
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        transformer = Transformer(context)
        transformed = transformer.visit(node)
        return str(transformed)

    def _normalize(self, query: str) -> str:
        node = parse_select(query)
        assert isinstance(node, ast.SelectQuery)
        return str(node)

    def test_basic_transformation(self):
        original_query = """
            SELECT uniqExact(person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp)
        """
        transformed = self._parse_and_transform(original_query)

        # Check that transformation occurred
        assert PREAGGREGATED_DAILY_UNIQUE_PERSONS_PAGEVIEWS_TABLE_NAME in transformed
        assert "uniqExactMerge" in transformed
        assert "uniq_exact_state" in transformed
        assert "time_window_start" in transformed

        # Original elements should not be present
        assert "events" not in transformed
        assert "toStartOfDay(timestamp)" not in transformed

        self.assertQueryMatchesSnapshot(transformed)

    def test_basic_transformation_count_distinct(self):
        original_query = """
            SELECT count(DISTINCT person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp)
        """
        transformed = self._parse_and_transform(original_query)

        # Check that transformation occurred
        assert PREAGGREGATED_DAILY_UNIQUE_PERSONS_PAGEVIEWS_TABLE_NAME in transformed
        assert "uniqExactMerge" in transformed
        assert "uniq_exact_state" in transformed
        assert "time_window_start" in transformed

        # Original elements should not be present
        assert "events" not in transformed
        assert "toStartOfDay(timestamp)" not in transformed

        self.assertQueryMatchesSnapshot(transformed)

    def test_preserves_alias(self):
        original_query = """
            SELECT uniqExact(person_id) AS unique_persons
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp)
        """
        transformed = self._parse_and_transform(original_query)

        # Alias should be preserved
        assert "unique_persons" in transformed
        self.assertQueryMatchesSnapshot(transformed)

    def test_preserves_order_by(self):
        original_query = """
            SELECT uniqExact(person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp)
            ORDER BY toStartOfDay(timestamp) DESC
        """
        transformed = self._parse_and_transform(original_query)

        assert PREAGGREGATED_DAILY_UNIQUE_PERSONS_PAGEVIEWS_TABLE_NAME in transformed
        assert "ORDER BY" in transformed
        self.assertQueryMatchesSnapshot(transformed)

    def test_preserves_limit(self):
        original_query = """
            SELECT uniqExact(person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp)
            LIMIT 10
        """
        transformed = self._parse_and_transform(original_query)

        assert PREAGGREGATED_DAILY_UNIQUE_PERSONS_PAGEVIEWS_TABLE_NAME in transformed
        assert "LIMIT 10" in transformed
        self.assertQueryMatchesSnapshot(transformed)

    def test_no_transformation_for_non_matching_query(self):
        original_query = """
            SELECT count(*)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp)
        """
        transformed = self._parse_and_transform(original_query)

        # Should not be transformed
        assert PREAGGREGATED_DAILY_UNIQUE_PERSONS_PAGEVIEWS_TABLE_NAME not in transformed
        assert transformed == self._normalize(original_query)

    def test_count_distinct_variant(self):
        original_query = """
            SELECT count(DISTINCT person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp)
        """
        transformed = self._parse_and_transform(original_query)

        assert PREAGGREGATED_DAILY_UNIQUE_PERSONS_PAGEVIEWS_TABLE_NAME in transformed
        assert "uniqExactMerge" in transformed
        self.assertQueryMatchesSnapshot(transformed)

    def test_nested_select(self):
        original_query = """
             SELECT sum(unique_persons) FROM (
                SELECT uniqExact(person_id) AS unique_persons
                FROM events
                WHERE event = '$pageview'
                  AND timestamp >= '2024-01-01'
                  AND timestamp < '2024-02-01'
                GROUP BY toStartOfDay(timestamp)
            )
        """
        transformed = self._parse_and_transform(original_query)

        # Inner query should be transformed
        assert PREAGGREGATED_DAILY_UNIQUE_PERSONS_PAGEVIEWS_TABLE_NAME in transformed
        assert "uniqExactMerge" in transformed
        self.assertQueryMatchesSnapshot(transformed)

    def test_date_extraction(self):
        """Test that date range is correctly extracted and used in WHERE clause."""
        original_query = """
            SELECT uniqExact(person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-06-15'
              AND timestamp < '2024-07-20'
            GROUP BY toStartOfDay(timestamp)
        """
        transformed = self._parse_and_transform(original_query)

        # Check that the date range is in the transformed query
        assert "2024-06-15" in transformed
        assert "2024-07-20" in transformed
        self.assertQueryMatchesSnapshot(transformed)

    def test_single_breakdown_transformation(self):
        """Test that breakdown dimensions are mapped to arrayElement calls."""
        original_query = """
            SELECT uniqExact(person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp), properties.$browser
        """
        transformed = self._parse_and_transform(original_query)

        # Check that transformation occurred
        assert PREAGGREGATED_DAILY_UNIQUE_PERSONS_PAGEVIEWS_TABLE_NAME in transformed
        assert "uniqExactMerge" in transformed

        # Check that the breakdown is mapped to arrayElement
        assert "arrayElement(breakdown_value, 1)" in transformed
        assert "time_window_start" in transformed

        # Original property reference should not be in transformed query
        assert "properties.$browser" not in transformed

        self.assertQueryMatchesSnapshot(transformed)

    def test_multiple_breakdowns_transformation(self):
        """Test that multiple breakdown dimensions are mapped to arrayElement calls."""
        original_query = """
            SELECT uniqExact(person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp), properties.$browser, properties.$os
        """
        transformed = self._parse_and_transform(original_query)

        # Check that transformation occurred
        assert PREAGGREGATED_DAILY_UNIQUE_PERSONS_PAGEVIEWS_TABLE_NAME in transformed
        assert "uniqExactMerge" in transformed

        # Check that both breakdowns are mapped to arrayElement with correct indices
        assert "arrayElement(breakdown_value, 1)" in transformed
        assert "arrayElement(breakdown_value, 2)" in transformed
        assert "time_window_start" in transformed

        # Original property references should not be in transformed query
        assert "properties.$browser" not in transformed
        assert "properties.$os" not in transformed

        self.assertQueryMatchesSnapshot(transformed)

    def test_breakdown_with_aliases(self):
        """Test that aliases on breakdown dimensions are preserved."""
        original_query = """
            SELECT uniqExact(person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp) AS day, properties.$browser AS browser, properties.$os AS os
        """
        transformed = self._parse_and_transform(original_query)

        # Check that transformation occurred
        assert PREAGGREGATED_DAILY_UNIQUE_PERSONS_PAGEVIEWS_TABLE_NAME in transformed
        assert "uniqExactMerge" in transformed

        # Check that breakdowns are mapped with preserved aliases
        assert "arrayElement(breakdown_value, 1)" in transformed
        assert "arrayElement(breakdown_value, 2)" in transformed
        assert "AS browser" in transformed or "browser" in transformed
        assert "AS os" in transformed or "os" in transformed

        self.assertQueryMatchesSnapshot(transformed)


class TestPreaggregationResultsEquivalence(BaseTest):
    """Integration tests to verify preaggregated results match raw query results."""

    def test_results_equivalent_with_and_without_preaggregation(self):
        """
        Verify that querying with usePreaggregatedIntermediateResults=True
        produces the same results as querying with it set to False.
        """

        # Create test events
        person_ids = [uuid4() for _ in range(5)]
        for i, person_id in enumerate(person_ids):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_{i}",
                timestamp=datetime(2024, 1, 15, 10, 0, 0),
                person_id=person_id,
            )

        # Insert corresponding preaggregated data
        # The preaggregation stores uniqExactState(person_id) as an aggregate state
        sync_execute(
            f"""
            INSERT INTO {SHARDED_PREAGGREGATION_RESULTS_TABLE()}
            (team_id, job_id, time_window_start, breakdown_value, uniq_exact_state)
            SELECT
                %(team_id)s,
                %(job_id)s,
                toDateTime('2024-01-15 00:00:00'),
                [],
                uniqExactState(person_id)
            FROM events
            WHERE team_id = %(team_id)s
              AND event = '$pageview'
              AND timestamp >= '2024-01-15'
              AND timestamp < '2024-01-16'
            """,
            {"team_id": self.team.pk, "job_id": uuid4()},
        )

        query = """
            SELECT uniqExact(person_id)
            FROM events
            WHERE event = '$pageview'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-02-01'
            GROUP BY toStartOfDay(timestamp)
        """

        # Query without preaggregation
        result_without = execute_hogql_query(
            query=query, team=self.team, modifiers=HogQLQueryModifiers(usePreaggregatedIntermediateResults=False)
        )

        # Query with preaggregation
        result_with = execute_hogql_query(
            query=query,
            team=self.team,
            modifiers=HogQLQueryModifiers(usePreaggregatedIntermediateResults=True),
        )

        assert result_without.results == result_with.results, (
            f"Results mismatch!\n"
            f"Without preaggregation: {result_without.results}\n"
            f"With preaggregation: {result_with.results}"
        )
