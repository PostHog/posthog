from typing import Optional, cast, Union
from posthog.constants import NON_TIME_SERIES_DISPLAY_TYPES
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team
from posthog.schema import BaseMathType, ChartDisplayType, EventsNode, ActionsNode, DataWarehouseNode
from posthog.models.filters.mixins.utils import cached_property
from posthog.hogql_queries.insights.data_warehouse_mixin import DataWarehouseInsightQueryMixin


class QueryAlternator:
    """Allows query_builder to modify the query without having to expost the whole AST interface"""

    _query: ast.SelectQuery
    _selects: list[ast.Expr]
    _group_bys: list[ast.Expr]
    _select_from: ast.JoinExpr | None

    def __init__(self, query: ast.SelectQuery | ast.SelectUnionQuery):
        assert isinstance(query, ast.SelectQuery)

        self._query = query
        self._selects = []
        self._group_bys = []
        self._select_from = None

    def build(self) -> ast.SelectQuery | ast.SelectUnionQuery:
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


class AggregationOperations(DataWarehouseInsightQueryMixin):
    team: Team
    series: Union[EventsNode, ActionsNode, DataWarehouseNode]
    chart_display_type: ChartDisplayType
    query_date_range: QueryDateRange
    is_total_value: bool

    def __init__(
        self,
        team: Team,
        series: Union[EventsNode, ActionsNode, DataWarehouseNode],
        chart_display_type: ChartDisplayType,
        query_date_range: QueryDateRange,
        is_total_value: bool,
    ) -> None:
        self.team = team
        self.series = series
        self.chart_display_type = chart_display_type
        self.query_date_range = query_date_range
        self.is_total_value = is_total_value

    @cached_property
    def _id_field(self) -> ast.Expr:
        if isinstance(self.series, DataWarehouseNode):
            return ast.Field(chain=["e", self.series.id_field])

        return ast.Field(chain=["e", "uuid"])

    def select_aggregation(self) -> ast.Expr:
        if self.series.math == "hogql" and self.series.math_hogql is not None:
            return parse_expr(self.series.math_hogql)
        elif self.series.math == "total":
            return parse_expr("count({id_field})", placeholders={"id_field": self._id_field})
        elif self.series.math == "dau":
            actor = "e.distinct_id" if self.team.aggregate_users_by_distinct_id else "e.person_id"
            return parse_expr(f"count(DISTINCT {actor})")
        elif self.series.math == "weekly_active":
            return ast.Placeholder(field="replaced")  # This gets replaced when doing query orchestration
        elif self.series.math == "monthly_active":
            return ast.Placeholder(field="replaced")  # This gets replaced when doing query orchestration
        elif self.series.math == "unique_session":
            return parse_expr('count(DISTINCT e."$session_id")')
        elif self.series.math == "unique_group" and self.series.math_group_type_index is not None:
            return parse_expr(f'count(DISTINCT e."$group_{int(self.series.math_group_type_index)}")')
        elif self.series.math_property is not None:
            if self.series.math == "avg":
                return self._math_func("avg", None)
            elif self.series.math == "sum":
                return self._math_func("sum", None)
            elif self.series.math == "min":
                return self._math_func("min", None)
            elif self.series.math == "max":
                return self._math_func("max", None)
            elif self.series.math == "median":
                return self._math_quantile(0.5, None)
            elif self.series.math == "p90":
                return self._math_quantile(0.9, None)
            elif self.series.math == "p95":
                return self._math_quantile(0.95, None)
            elif self.series.math == "p99":
                return self._math_quantile(0.99, None)

        return parse_expr(
            "count({id_field})", placeholders={"id_field": self._id_field}
        )  # All "count per actor" get replaced during query orchestration

    def actor_id(self) -> ast.Expr:
        if self.series.math == "unique_group" and self.series.math_group_type_index is not None:
            return parse_expr(f'e."$group_{int(self.series.math_group_type_index)}"')
        return parse_expr("e.person_id")

    def requires_query_orchestration(self) -> bool:
        math_to_return_true = [
            "weekly_active",
            "monthly_active",
        ]

        return self.is_count_per_actor_variant() or self.series.math in math_to_return_true

    def aggregating_on_session_duration(self) -> bool:
        return self.series.math_property == "$session_duration"

    def is_count_per_actor_variant(self):
        return self.series.math in [
            "avg_count_per_actor",
            "min_count_per_actor",
            "max_count_per_actor",
            "median_count_per_actor",
            "p90_count_per_actor",
            "p95_count_per_actor",
            "p99_count_per_actor",
        ]

    def is_active_users_math(self):
        return self.series.math in ["weekly_active", "monthly_active"]

    def _math_func(self, method: str, override_chain: Optional[list[str | int]]) -> ast.Call:
        if override_chain is not None:
            return ast.Call(name=method, args=[ast.Field(chain=override_chain)])

        if self.series.math_property == "$time":
            return ast.Call(
                name=method,
                args=[
                    ast.Call(
                        name="toUnixTimestamp",
                        args=[ast.Field(chain=["properties", "$time"])],
                    )
                ],
            )

        if self.series.math_property == "$session_duration":
            chain = ["session_duration"]
        elif isinstance(self.series, DataWarehouseNode) and self.series.math_property:
            chain = [self.series.math_property]
        else:
            chain = ["properties", self.series.math_property]

        return ast.Call(name=method, args=[ast.Field(chain=chain)])

    def _math_quantile(self, percentile: float, override_chain: Optional[list[str | int]]) -> ast.Call:
        if self.series.math_property == "$session_duration":
            chain = ["session_duration"]
        else:
            chain = ["properties", self.series.math_property]

        return ast.Call(
            name="quantile",
            params=[ast.Constant(value=percentile)],
            args=[ast.Field(chain=override_chain or chain)],
        )

    def _interval_placeholders(self):
        if self.series.math == "weekly_active":
            return {
                "exclusive_lookback": ast.Call(name="toIntervalDay", args=[ast.Constant(value=6)]),
                "inclusive_lookback": ast.Call(name="toIntervalDay", args=[ast.Constant(value=7)]),
            }
        elif self.series.math == "monthly_active":
            return {
                "exclusive_lookback": ast.Call(name="toIntervalDay", args=[ast.Constant(value=29)]),
                "inclusive_lookback": ast.Call(name="toIntervalDay", args=[ast.Constant(value=30)]),
            }

        return {
            "exclusive_lookback": ast.Call(name="toIntervalDay", args=[ast.Constant(value=0)]),
            "inclusive_lookback": ast.Call(name="toIntervalDay", args=[ast.Constant(value=0)]),
        }

    def _parent_select_query(
        self, inner_query: ast.SelectQuery | ast.SelectUnionQuery
    ) -> ast.SelectQuery | ast.SelectUnionQuery:
        if self.is_count_per_actor_variant():
            query = parse_select(
                "SELECT total FROM {inner_query}",
                placeholders={"inner_query": inner_query},
            )

            if not self.is_total_value:
                query.select.append(ast.Field(chain=["day_start"]))

            return query

        day_start = ast.Alias(
            alias="day_start",
            expr=ast.Call(
                name=f"toStartOf{self.query_date_range.interval_name.title()}", args=[ast.Field(chain=["timestamp"])]
            ),
        )

        query = cast(
            ast.SelectQuery,
            parse_select(
                """
                SELECT counts AS total
                FROM {inner_query}
                WHERE timestamp >= {date_from_start_of_interval} AND timestamp <= {date_to}
            """,
                placeholders={
                    **self.query_date_range.to_placeholders(),
                    "inner_query": inner_query,
                },
            ),
        )

        if self.is_total_value:
            query.select = [
                ast.Alias(
                    alias="total", expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["actor_id"])])
                )
            ]
        else:
            query.select.append(day_start)

        return query

    def _inner_select_query(
        self, cross_join_select_query: ast.SelectQuery | ast.SelectUnionQuery
    ) -> ast.SelectQuery | ast.SelectUnionQuery:
        if self.is_count_per_actor_variant():
            if self.series.math == "avg_count_per_actor":
                math_func = self._math_func("avg", ["total"])
            elif self.series.math == "min_count_per_actor":
                math_func = self._math_func("min", ["total"])
            elif self.series.math == "max_count_per_actor":
                math_func = self._math_func("max", ["total"])
            elif self.series.math == "median_count_per_actor":
                math_func = self._math_quantile(0.5, ["total"])
            elif self.series.math == "p90_count_per_actor":
                math_func = self._math_quantile(0.9, ["total"])
            elif self.series.math == "p95_count_per_actor":
                math_func = self._math_quantile(0.95, ["total"])
            elif self.series.math == "p99_count_per_actor":
                math_func = self._math_quantile(0.99, ["total"])
            else:
                raise NotImplementedError()

            total_alias = ast.Alias(alias="total", expr=math_func)

            query = parse_select(
                """
                    SELECT
                        {total_alias}
                    FROM {inner_query}
                """,
                placeholders={
                    "inner_query": cross_join_select_query,
                    "total_alias": total_alias,
                },
            )

            if not self.is_total_value:
                query.select.append(ast.Field(chain=["day_start"]))
                query.group_by = [ast.Field(chain=["day_start"])]

            return query

        query = cast(
            ast.SelectQuery,
            parse_select(
                """
                SELECT
                    d.timestamp,
                    COUNT(DISTINCT actor_id) AS counts
                FROM (
                    SELECT
                        {date_to_start_of_interval} - {number_interval_period} AS timestamp
                    FROM
                        numbers(dateDiff({interval}, {date_from_start_of_interval} - {inclusive_lookback}, {date_to}))
                ) d
                CROSS JOIN {cross_join_select_query} e
                WHERE
                    e.timestamp <= d.timestamp + INTERVAL 1 DAY AND
                    e.timestamp > d.timestamp - {exclusive_lookback}
                GROUP BY d.timestamp
                ORDER BY d.timestamp
            """,
                placeholders={
                    **self.query_date_range.to_placeholders(),
                    **self._interval_placeholders(),
                    "cross_join_select_query": cross_join_select_query,
                },
            ),
        )

        if self.is_total_value:
            query.select = [ast.Field(chain=["d", "timestamp"]), ast.Field(chain=["actor_id"])]
            query.group_by.append(ast.Field(chain=["actor_id"]))

        return query

    def _events_query(
        self, events_where_clause: ast.Expr, sample_value: ast.RatioExpr
    ) -> ast.SelectQuery | ast.SelectUnionQuery:
        date_from_with_lookback = "{date_from} - {inclusive_lookback}"
        if self.chart_display_type in NON_TIME_SERIES_DISPLAY_TYPES and self.series.math in (
            BaseMathType.weekly_active,
            BaseMathType.monthly_active,
        ):
            # TRICKY: On total value (non-time-series) insights, WAU/MAU math is simply meaningless.
            # There's no intuitive way to define the semantics of such a combination, so what we do is just turn it
            # into a count of unique users between `date_to - INTERVAL (7|30) DAY` and `date_to`.
            # This way we at least ensure the date range is the probably expected 7 or 30 days.
            date_from_with_lookback = "{date_to} - {inclusive_lookback}"

        date_filters = [
            parse_expr(
                f"timestamp >= {date_from_with_lookback}",
                placeholders={
                    **self.query_date_range.to_placeholders(),
                    **self._interval_placeholders(),
                },
            ),
            parse_expr(
                "timestamp <= {date_to}",
                placeholders={
                    **self.query_date_range.to_placeholders(),
                    **self._interval_placeholders(),
                },
            ),
        ]

        where_clause_combined = ast.And(exprs=[events_where_clause, *date_filters])

        if self.is_count_per_actor_variant():
            day_start = ast.Alias(
                alias="day_start",
                expr=ast.Call(
                    name=f"toStartOf{self.query_date_range.interval_name.title()}",
                    args=[ast.Field(chain=["timestamp"])],
                ),
            )

            query = parse_select(
                (
                    """
                    SELECT
                        count({id_field}) AS total
                    FROM {table} AS e
                    WHERE {events_where_clause}
                    GROUP BY {person_field}
                """
                    if isinstance(self.series, DataWarehouseNode)
                    else """
                    SELECT
                        count({id_field}) AS total
                    FROM events AS e
                    SAMPLE {sample}
                    WHERE {events_where_clause}
                    GROUP BY {person_field}
                """
                ),
                placeholders={
                    "id_field": self._id_field,
                    "table": self._table_expr,
                    "events_where_clause": where_clause_combined,
                    "sample": sample_value,
                    "person_field": ast.Field(
                        chain=["e", "distinct_id"] if self.team.aggregate_users_by_distinct_id else ["e", "person_id"]
                    ),
                },
            )

            if not self.is_total_value:
                query.select.append(day_start)
                query.group_by.append(ast.Field(chain=["day_start"]))

            return query

        return parse_select(
            """
                SELECT
                    timestamp as timestamp,
                    {person_field} AS actor_id
                FROM
                    events e
                SAMPLE {sample}
                WHERE {events_where_clause}
                GROUP BY
                    timestamp,
                    actor_id
            """,
            placeholders={
                "events_where_clause": where_clause_combined,
                "sample": sample_value,
                "person_field": ast.Field(
                    chain=["e", "distinct_id"] if self.team.aggregate_users_by_distinct_id else ["e", "person_id"]
                ),
            },
        )

    def get_query_orchestrator(self, events_where_clause: ast.Expr, sample_value: ast.RatioExpr):
        events_query = cast(ast.SelectQuery, self._events_query(events_where_clause, sample_value))
        inner_select = cast(ast.SelectQuery, self._inner_select_query(events_query))
        parent_select = cast(ast.SelectQuery, self._parent_select_query(inner_select))

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
