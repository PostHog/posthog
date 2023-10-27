from typing import List
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.schema import ActionsNode, EventsNode


class QueryAlternator:
    """Allows query_builder to modify the query without having to expost the whole AST interface"""

    _query: ast.SelectQuery
    _selects: List[ast.Expr]
    _group_bys: List[ast.Expr]
    _select_from: ast.JoinExpr | None

    def __init__(self, query: ast.SelectQuery):
        self._query = query
        self._selects = []
        self._group_bys = []
        self._select_from = None

    def build(self) -> ast.SelectQuery:
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

    def append_group_by(self, expr: ast.Expr) -> None:
        self._group_bys.append(expr)

    def replace_select_from(self, join_expr: ast.JoinExpr) -> None:
        self._select_from = join_expr


class AggregationOperations:
    series: EventsNode | ActionsNode
    query_date_range: QueryDateRange

    def __init__(self, series: str, query_date_range: QueryDateRange) -> None:
        self.series = series
        self.query_date_range = query_date_range

    def select_aggregation(self) -> ast.Expr:
        if self.series.math == "hogql":
            return parse_expr(self.series.math_hogql)
        elif self.series.math == "total":
            return parse_expr("count(e.uuid)")
        elif self.series.math == "dau":
            return parse_expr("count(DISTINCT e.person_id)")
        elif self.series.math == "weekly_active":
            return ast.Field(chain=["counts"])

        return parse_expr("count(e.uuid)")

    def requires_query_orchestration(self) -> bool:
        return self.series.math == "weekly_active"

    def _parent_select_query(self, inner_query: ast.SelectQuery) -> ast.SelectQuery:
        return parse_select(
            """
                SELECT
                    counts AS total,
                    dateTrunc({interval}, timestamp) AS day_start
                FROM {inner_query}
                WHERE timestamp >= {date_from} AND timestamp <= {date_to}
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "inner_query": inner_query,
            },
        )

    def _inner_select_query(self, cross_join_select_query: ast.SelectQuery) -> ast.SelectQuery:
        return parse_select(
            """
                SELECT
                    d.timestamp,
                    COUNT(DISTINCT actor_id) AS counts
                FROM (
                    SELECT
                        toStartOfDay({date_to}) - toIntervalDay(number) AS timestamp
                    FROM
                        numbers(dateDiff('day', toStartOfDay({date_from} - INTERVAL 7 DAY), {date_to}))
                ) d
                CROSS JOIN {cross_join_select_query} e
                WHERE
                    e.timestamp <= d.timestamp + INTERVAL 1 DAY AND
                    e.timestamp > d.timestamp - INTERVAL 6 DAY
                GROUP BY d.timestamp
                ORDER BY d.timestamp
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "cross_join_select_query": cross_join_select_query,
            },
        )

    def _events_query(self, events_where_clause: ast.Expr, sample_value: ast.RatioExpr) -> ast.SelectQuery:
        return parse_select(
            """
                SELECT
                    timestamp as timestamp,
                    e.person_id AS actor_id
                FROM
                    events e
                SAMPLE {sample}
                WHERE {events_where_clause}
                GROUP BY
                    timestamp,
                    actor_id
            """,
            placeholders={
                "events_where_clause": events_where_clause,
                "sample": sample_value,
            },
        )

    def get_query_orchestrator(self, events_where_clause: ast.Expr, sample_value: str):
        events_query = self._events_query(events_where_clause, sample_value)
        inner_select = self._inner_select_query(events_query)
        parent_select = self._parent_select_query(inner_select)

        class QueryOrchestrator:
            events_query_builder: QueryAlternator
            inner_select_query_builder: QueryAlternator
            parent_select_query_builder: QueryAlternator

            def __init__(self):
                self.events_query_builder = QueryAlternator(events_query)
                self.inner_select_query_builder = QueryAlternator(inner_select)
                self.parent_select_query_builder = QueryAlternator(parent_select)

            def build(self):
                self.events_query_builder.build()
                self.inner_select_query_builder.build()
                self.parent_select_query_builder.build()

                return parent_select

        return QueryOrchestrator()
