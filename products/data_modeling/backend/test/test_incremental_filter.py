from datetime import UTC, datetime

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import clear_locations

from products.data_modeling.backend.logic.incremental_filter import (
    GUARD_ALIAS,
    IncrementalFilterError,
    inject_incremental_filter,
)

SINCE = datetime(2026, 8, 1, tzinfo=UTC)


def _inner_selects(node: ast.Expr) -> list[ast.SelectQuery]:
    """The user's own query, unwrapped from the outer guard."""
    assert isinstance(node, ast.SelectQuery)
    assert node.select_from is not None
    inner = node.select_from.table
    if isinstance(inner, ast.SelectQuery):
        return [inner]
    assert isinstance(inner, ast.SelectSetQuery)
    return [branch for branch in inner.select_queries() if isinstance(branch, ast.SelectQuery)]


def _where_terms(select: ast.SelectQuery) -> list[ast.Expr]:
    if select.where is None:
        return []
    if isinstance(select.where, ast.And):
        return list(select.where.exprs)
    return [select.where]


class TestInjectIncrementalFilter(BaseTest):
    @parameterized.expand(
        [
            (
                "aliased_expression",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day",
                "day",
                "toStartOfDay(timestamp)",
            ),
            (
                "bare_field",
                "SELECT timestamp, uuid FROM events",
                "timestamp",
                "timestamp",
            ),
            (
                "qualified_field",
                "SELECT events.timestamp, events.uuid FROM events",
                "timestamp",
                "events.timestamp",
            ),
        ]
    )
    def test_filters_on_the_key_defining_expression(self, _name: str, query: str, key: str, expected: str) -> None:
        """The predicate has to target the expression, not the alias.

        Filtering `toStartOfDay(timestamp) >= watermark` pulls in every row of every touched day,
        so a grouped bucket is recomputed whole. Filtering the raw timestamp instead would
        recompute a partial day and overwrite the full count with it.
        """
        node = inject_incremental_filter(query, incremental_key=key, since=SINCE)

        (inner,) = _inner_selects(node)
        terms = _where_terms(inner)
        assert len(terms) == 1
        predicate = terms[0]
        assert isinstance(predicate, ast.CompareOperation)
        assert predicate.op == ast.CompareOperationOp.GtEq
        expected_select = parse_select(f"SELECT {expected}")
        assert isinstance(expected_select, ast.SelectQuery)
        assert clear_locations(predicate.left) == clear_locations(expected_select.select[0])
        assert predicate.right == ast.Constant(value=SINCE)

    def test_preserves_an_existing_where(self) -> None:
        node = inject_incremental_filter(
            "SELECT toStartOfDay(timestamp) AS day FROM events WHERE event = 'x' GROUP BY day",
            incremental_key="day",
            since=SINCE,
        )

        (inner,) = _inner_selects(node)
        terms = _where_terms(inner)
        assert len(terms) == 2, "the user's own filter must survive alongside the injected one"

    def test_filters_every_union_branch(self) -> None:
        """A branch without the filter would rescan all of history and write rows outside the window."""
        node = inject_incremental_filter(
            "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day "
            "UNION ALL "
            "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day",
            incremental_key="day",
            since=SINCE,
        )

        branches = _inner_selects(node)
        assert len(branches) == 2
        for branch in branches:
            assert len(_where_terms(branch)) == 1

    def test_wraps_the_result_in_an_output_guard(self) -> None:
        """Belt and braces: even if the pushed-down predicate lands somewhere the planner cannot
        fully honour, no row outside the window can reach the table."""
        node = inject_incremental_filter(
            "SELECT toStartOfDay(timestamp) AS day FROM events GROUP BY day",
            incremental_key="day",
            since=SINCE,
        )

        assert isinstance(node, ast.SelectQuery)
        assert node.select_from is not None
        assert node.select_from.alias == GUARD_ALIAS
        assert node.where == ast.CompareOperation(
            left=ast.Field(chain=[GUARD_ALIAS, "day"]),
            right=ast.Constant(value=SINCE),
            op=ast.CompareOperationOp.GtEq,
        )

    def test_rejects_a_key_the_query_does_not_produce(self) -> None:
        with self.assertRaises(IncrementalFilterError):
            inject_incremental_filter(
                "SELECT event, count() AS c FROM events GROUP BY event",
                incremental_key="day",
                since=SINCE,
            )

    # Regression: `SELECT *` planned incremental (eligibility expands the star) but the filter
    # raised on every run, so the retry silently rebuilt the whole table each time. The star's
    # qualifier must survive into the key: with a join in scope a bare name is ambiguous, and the
    # ambiguity error would fail every incremental run.
    @parameterized.expand(
        [
            ("bare_star", "SELECT * FROM events", ["timestamp"]),
            ("qualified_star", "SELECT e.* FROM events e", ["e", "timestamp"]),
            (
                "joined_qualified_star",
                "SELECT e.* FROM events e JOIN persons p ON e.person_id = p.id",
                ["e", "timestamp"],
            ),
            ("star_union_branch", "SELECT * FROM events UNION ALL SELECT * FROM events", ["timestamp"]),
        ]
    )
    def test_a_star_select_filters_on_the_key_by_name(self, _name: str, query: str, chain: list[str]) -> None:
        node = inject_incremental_filter(query, incremental_key="timestamp", since=SINCE)

        for branch in _inner_selects(node):
            terms = _where_terms(branch)
            assert len(terms) == 1
            predicate = terms[0]
            assert isinstance(predicate, ast.CompareOperation)
            assert clear_locations(predicate.left) == ast.Field(chain=list(chain))
            assert predicate.right == ast.Constant(value=SINCE)
