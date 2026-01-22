from typing import Any

import pytest
from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import HogQLQueryModifiers
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_and_print_ast
from posthog.hogql.test.utils import pretty_print_in_tests
from posthog.hogql.transforms.events_predicate_pushdown import EventsPredicatePushdownTransform


class TestEventsPredicatePushdownTransform(BaseTest):
    snapshot: Any
    maxDiff = None

    def _print_select(self, select: str, modifiers: HogQLQueryModifiers | None = None):
        expr = parse_select(select)
        query, _ = prepare_and_print_ast(
            expr,
            HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=modifiers if modifiers is not None else HogQLQueryModifiers(),
            ),
            "clickhouse",
        )
        return pretty_print_in_tests(query, self.team.pk)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_with_session_join_and_timestamp_filter(self):
        """Pushes timestamp filter into subquery when events table has lazy session join."""
        printed = self._print_select(
            "SELECT event, session.$session_duration FROM events WHERE timestamp >= '2024-01-01'"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_with_alias_and_session_join(self):
        """Preserves events table alias in the subquery wrapper."""
        printed = self._print_select(
            "SELECT e.event, session.$session_duration FROM events AS e WHERE e.timestamp >= '2024-01-01'"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_without_join_no_pushdown(self):
        """No pushdown when there are no lazy joins."""
        printed = self._print_select("SELECT event FROM events WHERE timestamp >= '2024-01-01'")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_without_where_no_pushdown(self):
        """No pushdown when there is no WHERE clause."""
        printed = self._print_select("SELECT event, session.$session_duration FROM events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_session_duration_filter_stays_in_outer_where(self):
        """Session duration filters cannot be pushed down and stay in outer WHERE."""
        printed = self._print_select(
            "SELECT event, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01' AND session.$session_duration > 0"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_multiple_pushable_predicates(self):
        """Multiple events-table predicates can be pushed down together."""
        printed = self._print_select(
            "SELECT event, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01' AND event = '$pageview'"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_subquery_with_pushdown(self):
        """Subquery pushdown"""
        printed = self._print_select(
            "SELECT event, avg($session_duration) FROM ("
            "SELECT event, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01' AND (event = '$pageview' OR event = '$pageleave')"
            ") GROUP BY event"
        )
        assert printed == self.snapshot


class TestEventsPredicatePushdownTransformUnit:
    """Unit tests for helper methods that don't require database/context."""

    def _make_events_select_with_join(
        self, where_clause: ast.Expr | None = None, alias: str | None = None, sample: ast.SampleExpr | None = None
    ) -> ast.SelectQuery:
        """Create a minimal SELECT query from events with a join for testing."""
        events_field = ast.Field(chain=["events"])

        mock_join = ast.JoinExpr(
            join_type="LEFT JOIN",
            table=ast.SelectQuery(
                select=[ast.Field(chain=["*"])],
                select_from=ast.JoinExpr(table=ast.Field(chain=["sessions"])),
            ),
            alias="events__session",
        )

        select_from = ast.JoinExpr(
            table=events_field,
            alias=alias,
            next_join=mock_join,
            sample=sample,
        )

        return ast.SelectQuery(
            select=[ast.Field(chain=["event"])],
            select_from=select_from,
            where=where_clause,
        )

    def test_should_apply_pushdown_with_valid_query(self):
        where_clause = ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value="2024-01-01"),
        )
        node = self._make_events_select_with_join(where_clause=where_clause)

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        assert transform._should_apply_pushdown(node) is True

    def test_should_not_apply_pushdown_without_where(self):
        node = self._make_events_select_with_join(where_clause=None)

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        assert transform._should_apply_pushdown(node) is False

    def test_should_not_apply_pushdown_without_joins(self):
        events_field = ast.Field(chain=["events"])
        select_from = ast.JoinExpr(table=events_field, next_join=None)
        node = ast.SelectQuery(
            select=[ast.Field(chain=["event"])],
            select_from=select_from,
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value="2024-01-01"),
            ),
        )

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        assert transform._should_apply_pushdown(node) is False

    def test_should_not_apply_pushdown_for_non_events_table(self):
        persons_field = ast.Field(chain=["persons"])
        mock_join = ast.JoinExpr(
            join_type="LEFT JOIN",
            table=ast.Field(chain=["other"]),
            alias="other_alias",
        )
        select_from = ast.JoinExpr(table=persons_field, next_join=mock_join)
        node = ast.SelectQuery(
            select=[ast.Field(chain=["id"])],
            select_from=select_from,
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["created_at"]),
                right=ast.Constant(value="2024-01-01"),
            ),
        )

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        assert transform._should_apply_pushdown(node) is False

    def test_should_not_apply_pushdown_with_sample_clause(self):
        sample = ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=1), right=ast.Constant(value=10)))
        where_clause = ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value="2024-01-01"),
        )
        node = self._make_events_select_with_join(where_clause=where_clause, sample=sample)

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        assert transform._should_apply_pushdown(node) is False

    def test_collect_joined_aliases_single_join(self):
        node = self._make_events_select_with_join(where_clause=ast.Constant(value=True))

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        aliases = transform._collect_joined_aliases(node)

        assert aliases == {"events__session"}

    def test_collect_joined_aliases_multiple_joins(self):
        events_field = ast.Field(chain=["events"])
        third_join = ast.JoinExpr(
            join_type="LEFT JOIN",
            table=ast.Field(chain=["cohorts"]),
            alias="events__cohort",
        )
        second_join = ast.JoinExpr(
            join_type="LEFT JOIN",
            table=ast.Field(chain=["persons"]),
            alias="events__person",
            next_join=third_join,
        )
        first_join = ast.JoinExpr(
            join_type="LEFT JOIN",
            table=ast.Field(chain=["sessions"]),
            alias="events__session",
            next_join=second_join,
        )
        select_from = ast.JoinExpr(table=events_field, next_join=first_join)
        node = ast.SelectQuery(
            select=[ast.Field(chain=["event"])],
            select_from=select_from,
            where=ast.Constant(value=True),
        )

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        aliases = transform._collect_joined_aliases(node)

        assert aliases == {"events__session", "events__person", "events__cohort"}

    def test_collect_joined_aliases_empty_when_no_joins(self):
        events_field = ast.Field(chain=["events"])
        select_from = ast.JoinExpr(table=events_field, next_join=None)
        node = ast.SelectQuery(
            select=[ast.Field(chain=["event"])],
            select_from=select_from,
            where=ast.Constant(value=True),
        )

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        aliases = transform._collect_joined_aliases(node)

        assert aliases == set()
