from typing import Any

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.transforms.where_clause_pushdown import push_down_where_clauses


class TestWhereClausePushdown(BaseTest):
    snapshot: Any

    def _make_inner_query(self, select_fields: list[str], table_name: str = "events") -> ast.SelectQuery:
        return ast.SelectQuery(
            select=[ast.Alias(alias=f, expr=ast.Field(chain=[table_name, f])) for f in select_fields],
            select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        )

    def _make_outer_query(self, inner_query: ast.SelectQuery, where: ast.Expr) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=[ast.Field(chain=["*"])],
            select_from=ast.JoinExpr(table=inner_query, alias="inner"),
            where=where,
        )

    def test_simple_field_pushdown(self):
        """WHERE clause on a field that exists in inner query should be pushed down"""
        inner = self._make_inner_query(["team_id", "event"])
        outer = self._make_outer_query(
            inner,
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["team_id"]),
                right=ast.Constant(value=1),
            ),
        )

        push_down_where_clauses(outer, inner, outer_table_alias="inner", inner_table_name="events")

        assert inner.where is not None
        assert isinstance(inner.where, ast.CompareOperation)
        assert inner.where.op == ast.CompareOperationOp.Eq

    def test_alias_field_pushdown(self):
        """WHERE clause using an alias should resolve and push down"""
        inner = ast.SelectQuery(
            select=[ast.Alias(alias="tid", expr=ast.Field(chain=["events", "team_id"]))],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        )
        outer = self._make_outer_query(
            inner,
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["tid"]),
                right=ast.Constant(value=1),
            ),
        )

        push_down_where_clauses(outer, inner, outer_table_alias="inner", inner_table_name="events")

        assert inner.where is not None

    def test_preserves_existing_inner_where(self):
        """Existing inner WHERE should be preserved and combined with pushed down clause"""
        inner = self._make_inner_query(["team_id", "event"])
        inner.where = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["events", "event"]),
            right=ast.Constant(value="$pageview"),
        )
        outer = self._make_outer_query(
            inner,
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["team_id"]),
                right=ast.Constant(value=1),
            ),
        )

        push_down_where_clauses(outer, inner, outer_table_alias="inner", inner_table_name="events")

        assert inner.where is not None
        assert isinstance(inner.where, ast.And)
        assert len(inner.where.exprs) == 2

    def test_multiple_conditions_pushdown(self):
        """Multiple AND conditions should all be pushed down if eligible"""
        inner = self._make_inner_query(["team_id", "event"])
        outer = self._make_outer_query(
            inner,
            where=ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["team_id"]),
                        right=ast.Constant(value=1),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["event"]),
                        right=ast.Constant(value="$pageview"),
                    ),
                ]
            ),
        )

        push_down_where_clauses(outer, inner, outer_table_alias="inner", inner_table_name="events")

        assert inner.where is not None
        assert isinstance(inner.where, ast.And)
        assert len(inner.where.exprs) == 2

    def test_no_pushdown_for_non_matching_field(self):
        """WHERE clause on field not in inner query should not be pushed down"""
        inner = self._make_inner_query(["team_id", "event"])
        outer = self._make_outer_query(
            inner,
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["unknown_field"]),
                right=ast.Constant(value=1),
            ),
        )

        push_down_where_clauses(outer, inner, outer_table_alias="inner", inner_table_name="events")

        assert inner.where is None

    def test_partial_pushdown_mixed_conditions(self):
        """Only eligible conditions should be pushed down, others remain"""
        inner = self._make_inner_query(["team_id", "event"])
        outer = self._make_outer_query(
            inner,
            where=ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["team_id"]),
                        right=ast.Constant(value=1),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["unknown_field"]),
                        right=ast.Constant(value="test"),
                    ),
                ]
            ),
        )

        push_down_where_clauses(outer, inner, outer_table_alias="inner", inner_table_name="events")

        assert inner.where is not None
        assert isinstance(inner.where, ast.CompareOperation)

    def test_no_pushdown_without_where(self):
        """No error when outer query has no WHERE"""
        inner = self._make_inner_query(["team_id", "event"])
        outer = ast.SelectQuery(
            select=[ast.Field(chain=["*"])],
            select_from=ast.JoinExpr(table=inner, alias="inner"),
        )

        push_down_where_clauses(outer, inner, outer_table_alias="inner", inner_table_name="events")

        assert inner.where is None

    def test_qualified_field_pushdown(self):
        """WHERE clause with table-qualified field should be pushed down"""
        inner = self._make_inner_query(["team_id", "event"])
        outer = self._make_outer_query(
            inner,
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["inner", "team_id"]),
                right=ast.Constant(value=1),
            ),
        )

        push_down_where_clauses(outer, inner, outer_table_alias="inner", inner_table_name="events")

        assert inner.where is not None

    @parameterized.expand(
        [
            ("greater_than", ast.CompareOperationOp.Gt),
            ("less_than", ast.CompareOperationOp.Lt),
            ("not_equals", ast.CompareOperationOp.NotEq),
            ("greater_or_equals", ast.CompareOperationOp.GtEq),
            ("less_or_equals", ast.CompareOperationOp.LtEq),
        ]
    )
    def test_various_comparison_operators_pushdown(self, name: str, op: ast.CompareOperationOp):
        """Various comparison operators should be pushed down"""
        inner = self._make_inner_query(["team_id", "event"])
        outer = self._make_outer_query(
            inner,
            where=ast.CompareOperation(
                op=op,
                left=ast.Field(chain=["team_id"]),
                right=ast.Constant(value=1),
            ),
        )

        push_down_where_clauses(outer, inner, outer_table_alias="inner", inner_table_name="events")

        assert inner.where is not None
        assert isinstance(inner.where, ast.CompareOperation)
        assert inner.where.op == op

    # Snapshot tests - show before/after HogQL output

    def _apply_pushdown(self, query: str) -> tuple[str, str]:
        """Parse query, apply pushdown, return (before, after) HogQL strings."""
        outer = parse_select(query)
        before = outer.to_hogql()

        inner = outer.select_from.table
        assert isinstance(inner, ast.SelectQuery)

        push_down_where_clauses(outer, inner, outer_table_alias="inner", inner_table_name="events")

        after = outer.to_hogql()
        return before, after

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_snapshot_simple_pushdown(self):
        """Simple WHERE clause pushed down to inner query"""
        before, after = self._apply_pushdown(
            "SELECT * FROM (SELECT team_id, event FROM events) AS inner WHERE team_id = 1"
        )
        assert {"before": before, "after": after} == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_snapshot_multiple_conditions(self):
        """Multiple AND conditions pushed down"""
        before, after = self._apply_pushdown(
            "SELECT * FROM (SELECT team_id, event FROM events) AS inner WHERE team_id = 1 AND event = '$pageview'"
        )
        assert {"before": before, "after": after} == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_snapshot_preserves_existing_inner_where(self):
        """Pushed down clause combined with existing inner WHERE"""
        before, after = self._apply_pushdown(
            "SELECT * FROM (SELECT team_id, event FROM events WHERE event = '$pageview') AS inner WHERE team_id = 1"
        )
        assert {"before": before, "after": after} == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_snapshot_partial_pushdown(self):
        """Only eligible conditions pushed down"""
        before, after = self._apply_pushdown(
            "SELECT * FROM (SELECT team_id, event FROM events) AS inner WHERE team_id = 1 AND unknown_field = 'test'"
        )
        assert {"before": before, "after": after} == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_snapshot_qualified_field_reference(self):
        """Table-qualified field reference rewritten correctly"""
        before, after = self._apply_pushdown(
            "SELECT * FROM (SELECT team_id, event FROM events) AS inner WHERE inner.team_id = 1"
        )
        assert {"before": before, "after": after} == self.snapshot
