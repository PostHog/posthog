from typing import cast

from posthog.hogql import ast


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
    ):
        self._filters = filters
        self._filters_with_breakdown = filters_with_breakdown
        self._is_first_matching_event = is_first_matching_event
        query.select = self._select_expr(date_from)
        query.select_from = self._select_from_expr(ratio)
        query.where = self._where_expr(date_to, event_or_action_filter)
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
            ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])
            if not self._is_first_matching_event or self._filters is None
            else ast.Call(name="minIf", args=[ast.Field(chain=["timestamp"]), self._filters])
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
                    args=[ast.Field(chain=["timestamp"]), aggregation_filters],
                ),
            ),
        ]

    def _select_from_expr(self, ratio: ast.RatioExpr | None = None) -> ast.JoinExpr:
        sample_value = ast.SampleExpr(sample_value=ratio) if ratio is not None else None
        return ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e", sample=sample_value)

    def _where_expr(self, date_to: ast.Expr, event_or_action_filter: ast.Expr | None = None) -> ast.Expr:
        where_filters = [date_to]
        if event_or_action_filter is not None:
            where_filters.append(event_or_action_filter)

        if len(where_filters) > 1:
            where_filters_expr = cast(ast.Expr, ast.And(exprs=where_filters))
        else:
            where_filters_expr = where_filters[0]
        return where_filters_expr

    def _group_by_expr(self) -> list[ast.Expr]:
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
            ast.Call(name="argMin", args=[column, ast.Field(chain=["timestamp"])])
            if not self._is_first_matching_event or self._filters is None
            else ast.Call(
                name="argMinIf",
                args=[column, ast.Field(chain=["timestamp"]), self._filters],
            )
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
