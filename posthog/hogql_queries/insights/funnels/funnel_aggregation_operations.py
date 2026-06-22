from typing import cast

from posthog.hogql import ast

from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.utils.aggregations import (
    FirstTimeForUserDataWarehouseConfig,
    FirstTimeForUserEventsQueryAlternator,
)
from posthog.hogql_queries.utils.query_date_range import QueryDateRange


class FirstTimeForUserAggregationQuery:
    _context: FunnelQueryContext
    _filters: ast.Expr | None
    _event_or_action_filter: ast.Expr | None
    _dwh_config: FirstTimeForUserDataWarehouseConfig | None

    def __init__(
        self,
        context: FunnelQueryContext,
        filters: ast.Expr | None = None,
        event_or_action_filter: ast.Expr | None = None,
        dwh_config: FirstTimeForUserDataWarehouseConfig | None = None,
    ):
        self._context = context
        self._filters = filters
        self._event_or_action_filter = event_or_action_filter
        self._dwh_config = dwh_config

    def to_query(self) -> ast.SelectQuery:
        query = ast.SelectQuery(
            select=[ast.Field(chain=["uuid"])],
            select_from=ast.JoinExpr(table=self._inner_query()),
        )
        return query

    def _inner_query(self) -> ast.SelectQuery | None:
        inner_query = ast.SelectQuery(select=[])
        builder = FirstTimeForUserEventsQueryAlternator(
            inner_query,
            self._date_from_expr(),
            self._date_to_expr(),
            self._filters,
            self._event_or_action_filter,
            self._ratio_expr(),
            dwh_config=self._dwh_config,
        )
        builder.append_select(self._select_expr(), aggregate=True)
        return cast(ast.SelectQuery, builder.build())

    def _select_expr(self):
        expr = self._dwh_config.id_select_expr if self._dwh_config is not None else ast.Field(chain=["uuid"])
        return ast.Alias(
            alias="uuid",
            expr=expr,
        )

    def _date_range(self) -> QueryDateRange:
        team, query, now = self._context.team, self._context.query, self._context.now
        date_range = QueryDateRange(
            date_range=query.dateRange,
            team=team,
            interval=query.interval,
            now=now,
        )
        return date_range

    def _timestamp_expr(self) -> ast.Expr:
        if self._dwh_config is not None:
            return self._dwh_config.timestamp_expr
        return ast.Field(chain=["timestamp"])

    def _date_to_expr(self) -> ast.Expr:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.LtEq,
            left=self._timestamp_expr(),
            right=ast.Constant(value=self._date_range().date_to()),
        )

    def _date_from_expr(self) -> ast.Expr:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=self._timestamp_expr(),
            right=ast.Constant(value=self._date_range().date_from()),
        )

    def _ratio_expr(self) -> ast.RatioExpr | None:
        query = self._context.query
        if query.samplingFactor is None:
            return None
        else:
            return ast.RatioExpr(left=ast.Constant(value=query.samplingFactor))
