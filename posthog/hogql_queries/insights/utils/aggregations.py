from dataclasses import dataclass
from typing import cast

from posthog.hogql import ast


@dataclass
class FirstTimeForUserDataWarehouseConfig:
    """Retargets the first-time-for-user subquery from the events table to a data warehouse table."""

    table_expr: ast.Field
    """The data warehouse table, e.g. ast.Field(chain=[table_name])."""
    timestamp_expr: ast.Expr
    """The timestamp column, e.g. e.<timestamp_field> (wrapped in toDateTime() for String columns)."""
    group_by_expr: ast.Expr
    """The aggregation target, e.g. parse_expr(aggregation_target_field)."""
    id_select_expr: ast.Expr
    """The row identifier, e.g. ast.Field(chain=[id_field]); becomes argMin(<id_field>, timestamp)."""


class QueryAlternator:
    """Allows query_builder to modify the query without having to expose the whole AST interface"""

    _query: ast.SelectQuery
    _selects: list[ast.Expr]
    _group_bys: list[ast.Expr]
    _select_from: ast.JoinExpr | None

    def __init__(self, query: ast.SelectQuery | ast.SelectSetQuery):
        assert isinstance(query, ast.SelectQuery)

        self._query = query
        self._selects = []
        self._group_bys = []
        self._select_from = None

    def build(self) -> ast.SelectQuery | ast.SelectSetQuery:
        if len(self._selects) > 0:
            self._query.select.extend(self._selects)

        if len(self._group_bys) > 0:
            if self._query.group_by is None:
                self._query.group_by = self._group_bys
            else:
                self._query.group_by.extend(self._group_bys)

        if self._select_from is not None:
            self._query.select_from = self._select_from

        return self._query

    def append_select(self, expr: ast.Expr) -> None:
        self._selects.append(expr)

    def extend_select(self, exprs: list[ast.Expr]) -> None:
        self._selects.extend(exprs)

    def append_group_by(self, expr: ast.Expr) -> None:
        self._group_bys.append(expr)

    def extend_group_by(self, exprs: list[ast.Expr]) -> None:
        self._group_bys.extend(exprs)

    def replace_select_from(self, join_expr: ast.JoinExpr) -> None:
        self._select_from = join_expr


class FirstTimeForUserEventsQueryAlternator(QueryAlternator):
    """
    A specialized QueryAlternator for building queries that identify the first time an event or action occurs for each user.

    This class extends the base QueryAlternator to build a query that:
    - Finds the minimum timestamp for `person_id` filtered by the event/action and right date range.
    - Compares it with the minimum timestamp that satisfies general conditions like event/person properties and the left date range.
    - Selects only those events where these two timestamps match.
    """

    def __init__(
        self,
        query: ast.SelectQuery,
        date_from: ast.Expr,
        date_to: ast.Expr,
        filters: ast.Expr | None = None,
        event_or_action_filter: ast.Expr | None = None,
        ratio: ast.RatioExpr | None = None,
        is_first_matching_event: bool = False,
        filters_with_breakdown: ast.Expr | None = None,
        dwh_config: FirstTimeForUserDataWarehouseConfig | None = None,
    ):
        self._filters = filters
        self._filters_with_breakdown = filters_with_breakdown
        self._is_first_matching_event = is_first_matching_event
        self._dwh_config = dwh_config
        query.select = self._select_expr(date_from)
        query.select_from = self._select_from_expr(ratio)
        query.where = self._where_expr(date_to, event_or_action_filter, self._matching_event_prefilter())
        query.group_by = self._group_by_expr()
        query.having = self._having_expr()
        super().__init__(query)

    def _select_expr(self, date_from: ast.Expr):
        min_timestamp_with_condition_filters = (
            self._filters_with_breakdown if self._filters_with_breakdown is not None else self._filters
        )
        aggregation_filters = (
            date_from
            if min_timestamp_with_condition_filters is None
            else ast.And(exprs=[date_from, min_timestamp_with_condition_filters])
        )

        min_timestamp_expr = (
            ast.Call(name="minIf", args=[self._timestamp_field(), cast(ast.Expr, self._filters)])
            if self._uses_conditional_aggregation()
            else ast.Call(name="min", args=[self._timestamp_field()])
        )

        return [
            ast.Alias(
                alias="min_timestamp",
                expr=min_timestamp_expr,
            ),
            ast.Alias(
                alias="min_timestamp_with_condition",
                expr=ast.Call(
                    name="minIf",
                    args=[self._timestamp_field(), aggregation_filters],
                ),
            ),
        ]

    def _timestamp_field(self) -> ast.Expr:
        if self._dwh_config is not None:
            return self._dwh_config.timestamp_expr
        return ast.Field(chain=["timestamp"])

    def _select_from_expr(self, ratio: ast.RatioExpr | None = None) -> ast.JoinExpr:
        sample_value = ast.SampleExpr(sample_value=ratio) if ratio is not None else None
        table_expr = self._dwh_config.table_expr if self._dwh_config is not None else ast.Field(chain=["events"])
        return ast.JoinExpr(table=table_expr, alias="e", sample=sample_value)

    def _uses_conditional_aggregation(self) -> bool:
        # first_matching_event_for_user wraps the series filters in conditional aggregates (minIf/argMinIf).
        return self._is_first_matching_event and self._filters is not None

    def _matching_event_prefilter(self) -> ast.Expr | None:
        # Only a first_matching_event can push series filters into WHERE; plain first_time must scan full history.
        return self._filters if self._uses_conditional_aggregation() else None

    def _where_expr(
        self,
        date_to: ast.Expr,
        event_or_action_filter: ast.Expr | None = None,
        prefilter: ast.Expr | None = None,
    ) -> ast.Expr:
        where_filters = [date_to]
        if event_or_action_filter is not None:
            where_filters.append(event_or_action_filter)
        if prefilter is not None:
            where_filters.append(prefilter)

        if len(where_filters) > 1:
            where_filters_expr = cast(ast.Expr, ast.And(exprs=where_filters))
        else:
            where_filters_expr = where_filters[0]
        return where_filters_expr

    def _group_by_expr(self) -> list[ast.Expr]:
        if self._dwh_config is not None:
            return [self._dwh_config.group_by_expr]
        return [ast.Field(chain=["person_id"])]

    def _having_expr(self) -> ast.Expr:
        left = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["min_timestamp"]),
            right=ast.Field(chain=["min_timestamp_with_condition"]),
        )
        right = ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq,
            left=ast.Field(chain=["min_timestamp"]),
            right=ast.Call(name="fromUnixTimestamp", args=[ast.Constant(value=0)]),
        )

        return ast.And(exprs=[left, right])

    def _transform_column(self, column: ast.Expr):
        return (
            ast.Call(
                name="argMinIf",
                args=[column, self._timestamp_field(), cast(ast.Expr, self._filters)],
            )
            if self._uses_conditional_aggregation()
            else ast.Call(name="argMin", args=[column, self._timestamp_field()])
        )

    def append_select(self, expr: ast.Expr, aggregate: bool = False):
        if aggregate:
            if isinstance(expr, ast.Alias):
                expr = ast.Alias(expr=self._transform_column(expr.expr), alias=expr.alias)
            else:
                expr = self._transform_column(expr)
        super().append_select(expr)

    def extend_select(self, exprs: list[ast.Expr], aggregate: bool = False) -> None:
        for expr in exprs:
            self.append_select(expr, aggregate)
