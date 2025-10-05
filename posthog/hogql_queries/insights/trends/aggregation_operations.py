from typing import Optional, Union, cast

from posthog.schema import ActionsNode, BaseMathType, ChartDisplayType, DataWarehouseNode, EventsNode

from posthog.hogql import ast
from posthog.hogql.base import Expr
from posthog.hogql.database.schema.exchange_rate import convert_currency_call
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.placeholders import replace_placeholders

from posthog.constants import NON_TIME_SERIES_DISPLAY_TYPES
from posthog.hogql_queries.insights.data_warehouse_mixin import DataWarehouseInsightQueryMixin
from posthog.hogql_queries.insights.trends.utils import is_groups_math
from posthog.hogql_queries.insights.utils.aggregations import FirstTimeForUserEventsQueryAlternator, QueryAlternator
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team

DEFAULT_CURRENCY_VALUE = "USD"
DEFAULT_REVENUE_PROPERTY = "$revenue"


def create_placeholder(name: str) -> ast.Placeholder:
    return ast.Placeholder(expr=ast.Field(chain=[name]))


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

    def select_aggregation(self) -> ast.Expr:
        if self.series.math == "hogql" and self.series.math_hogql is not None:
            return parse_expr(self.series.math_hogql)
        elif self.series.math == "total" or self.series.math == "first_time_for_user":
            return parse_expr("count()")
        elif self.series.math == "dau":
            # `weekly_active` and `monthly_active` turn into `dau` for intervals longer than their period, hence the
            # need to use person field here so we need to get the actor accordingly.
            actor = self._get_person_field()
            return parse_expr(f"count(DISTINCT {actor})")
        elif self.series.math == "weekly_active":
            return create_placeholder("replaced")  # This gets replaced when doing query orchestration
        elif self.series.math == "monthly_active":
            return create_placeholder("replaced")  # This gets replaced when doing query orchestration
        elif self.series.math == "unique_session":
            return parse_expr('count(DISTINCT e."$session_id")')
        elif self.series.math == "unique_group" and self.series.math_group_type_index is not None:
            return parse_expr(f'count(DISTINCT e."$group_{int(self.series.math_group_type_index)}")')
        elif self.series.math_property is not None:
            if self.series.math == "avg":
                return self._math_func("avg")
            elif self.series.math == "sum":
                return self._math_func("sum")
            elif self.series.math == "min":
                return self._math_func("min")
            elif self.series.math == "max":
                return self._math_func("max")
            elif self.series.math == "median":
                return self._math_quantile(0.5)
            elif self.series.math == "p75":
                return self._math_quantile(0.75)
            elif self.series.math == "p90":
                return self._math_quantile(0.9)
            elif self.series.math == "p95":
                return self._math_quantile(0.95)
            elif self.series.math == "p99":
                return self._math_quantile(0.99)

        return parse_expr("count()")  # All "count per actor" get replaced during query orchestration

    @property
    def actor_id_field(self) -> str:
        """
        For group-based math (unique_group, weekly_active, monthly_active, dau with group index), returns the group
        field. Otherwise, returns person_id.

        Note: DAU can have math_group_type_index because weekly_active/monthly_active get converted to DAU when
        interval >= their time window.
        """
        if is_groups_math(series=self.series):
            return f'e."$group_{int(cast(int, self.series.math_group_type_index))}"'
        return "e.person_id"

    def actor_id(self) -> ast.Expr:
        return parse_expr(self.actor_id_field)

    def _get_person_field(self) -> str:
        """
        Similar to `actor_id_field` property, but here the aggregation option is factored in for `GROUP BY`s.
        `aggregate_users_by_distinct_id` only applies when the actor in question is a person.
        """
        if self.actor_id_field == "e.person_id":
            return "e.distinct_id" if self.team.aggregate_users_by_distinct_id else "e.person_id"
        return self.actor_id_field

    @property
    def person_field(self) -> Expr:
        return parse_expr(self._get_person_field())

    def requires_query_orchestration(self) -> bool:
        math_to_return_true = [
            "weekly_active",
            "monthly_active",
            "first_time_for_user",
            "first_matching_event_for_user",
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
            "p75_count_per_actor",
            "p90_count_per_actor",
            "p95_count_per_actor",
            "p99_count_per_actor",
        ]

    def is_active_users_math(self):
        return self.series.math in ["weekly_active", "monthly_active"]

    def is_first_time_ever_math(self):
        return self.series.math in {"first_time_for_user", "first_matching_event_for_user"}

    def is_first_matching_event(self):
        return self.series.math == "first_matching_event_for_user"

    def _get_math_chain(self) -> list[str | int]:
        if not self.series.math_property:
            raise ValueError("No math property set")
        if self.series.math_property == "$session_duration":
            return ["session_duration"]
        elif isinstance(self.series, DataWarehouseNode):
            return [self.series.math_property]
        elif self.series.math_property_type == "data_warehouse_person_properties":
            return ["person", *self.series.math_property.split(".")]
        elif self.series.math_property_type == "person_properties":
            return ["person", "properties", self.series.math_property]
        else:
            return ["properties", self.series.math_property]

    def _math_func(self, method: str, override_chain: Optional[list[str | int]] = None) -> ast.Call:
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

        chain = self._get_math_chain()

        if self.series.math_property_revenue_currency is not None:
            event_currency = (
                ast.Constant(value=self.series.math_property_revenue_currency.static.value)
                if self.series.math_property_revenue_currency.static is not None
                else ast.Field(chain=["properties", self.series.math_property_revenue_currency.property])
                if self.series.math_property_revenue_currency.property is not None
                else ast.Field(chain=["properties", DEFAULT_REVENUE_PROPERTY])
            )
            base_currency = (
                ast.Constant(value=self.team.base_currency)
                if self.team.base_currency is not None
                else ast.Constant(value=DEFAULT_CURRENCY_VALUE)
            )

            # For DataWarehouse nodes we have a timestamp field we need to use
            # This timestamp data can be nullable, so we need to handle NULL values
            # to avoid ClickHouse errors with dictGetOrDefault expecting non-nullable dates
            timestamp_expr: ast.Expr
            if isinstance(self.series, DataWarehouseNode):
                if self.series.dw_source_type == "self-managed":
                    # The database's automatic toDateTime wrapping causes parseDateTime64BestEffortOrNull issues
                    # for the timestamp field that are strings for self managed sources.
                    # We use today's date as the timestamp to avoid this issue.
                    timestamp_expr = ast.Call(name="today", args=[])
                else:
                    # Handle different timestamp field types in DataWarehouse
                    # Convert both to String format for coalesce, then _toDate will handle final conversion
                    timestamp_expr = ast.Call(
                        name="coalesce",
                        args=[
                            ast.Call(name="toString", args=[ast.Field(chain=[self.series.timestamp_field])]),
                            ast.Constant(value="1970-01-01"),
                        ],
                    )
            else:
                # For events, timestamp is never null
                timestamp_expr = ast.Field(chain=["timestamp"])

            # Apply math_multiplier to the field before currency conversion
            currency_field_expr: ast.Expr = ast.Field(chain=chain)
            if hasattr(self.series, "math_multiplier") and self.series.math_multiplier is not None:
                currency_field_expr = ast.ArithmeticOperation(
                    left=currency_field_expr,
                    right=ast.Constant(value=self.series.math_multiplier),
                    op=ast.ArithmeticOperationOp.Mult,
                )

            currency_field_expr = convert_currency_call(
                currency_field_expr,
                event_currency,
                base_currency,
                ast.Call(name="_toDate", args=[timestamp_expr]),
            )

            return ast.Call(name=method, args=[currency_field_expr])

        # Apply math_multiplier if present
        field_expr: ast.Expr = ast.Field(chain=chain)
        if hasattr(self.series, "math_multiplier") and self.series.math_multiplier is not None:
            field_expr = ast.ArithmeticOperation(
                left=field_expr,
                right=ast.Constant(value=self.series.math_multiplier),
                op=ast.ArithmeticOperationOp.Mult,
            )

        return ast.Call(
            # Two caveats here - similar to the math_quantile, but not quite:
            # 1. We always parse/convert the value to a Float64, to make sure it's a number. This truncates precision
            # of very large integers, but it's a tradeoff preventing queries failing with "Illegal type String"
            # 2. We fall back to 0 when there's no data, which is not quite kosher for math functions other than sum
            # (null would actually be more meaningful for e.g. min or max), but formulas aren't equipped to handle nulls
            name="ifNull",
            args=[
                ast.Call(name=method, args=[ast.Call(name="toFloat", args=[field_expr])]),
                ast.Constant(value=0),
            ],
        )

    def _math_quantile(self, percentile: float, override_chain: Optional[list[str | int]] = None) -> ast.Call:
        chain = override_chain or self._get_math_chain()

        # Apply math_multiplier if present
        field_expr: ast.Expr = ast.Field(chain=chain)
        if hasattr(self.series, "math_multiplier") and self.series.math_multiplier is not None:
            field_expr = ast.ArithmeticOperation(
                left=field_expr,
                right=ast.Constant(value=self.series.math_multiplier),
                op=ast.ArithmeticOperationOp.Mult,
            )

        return ast.Call(
            # Two caveats here - similar to the math_func, but not quite:
            # 1. We always parse/convert the value to a Float64, to make sure it's a number. This truncates precision
            # of very large integers, but it's a tradeoff preventing queries failing with "Illegal type String"
            # 2. We fall back to 0 when there's no data, which makes some kind of sense for percentile,
            # (null would actually be more meaningful for e.g. min or max), but formulas aren't equipped to handle nulls
            name="ifNull",
            args=[
                ast.Call(
                    name="quantile",
                    params=[ast.Constant(value=percentile)],
                    args=[ast.Call(name="toFloat", args=[field_expr])],
                ),
                ast.Constant(value=0),
            ],
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

    @property
    def _interval_function_name(self) -> str:
        return f"toStartOf{self.query_date_range.interval_name.title()}"

    def _actors_parent_select_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        if self.is_count_per_actor_variant():
            query = parse_select(
                "SELECT total FROM {inner_query}",
                placeholders={"inner_query": create_placeholder("inner_query")},
            )
            assert isinstance(query, ast.SelectQuery)

            if not self.is_total_value:
                query.select.append(ast.Field(chain=["day_start"]))

            return query

        day_start = ast.Alias(
            alias="day_start",
            expr=ast.Call(name=self._interval_function_name, args=[ast.Field(chain=["timestamp"])]),
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
                    "inner_query": create_placeholder("inner_query"),
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

    def _actors_inner_select_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        if self.is_count_per_actor_variant():
            if self.series.math == "avg_count_per_actor":
                math_func = self._math_func("avg", ["total"])
            elif self.series.math == "min_count_per_actor":
                math_func = self._math_func("min", ["total"])
            elif self.series.math == "max_count_per_actor":
                math_func = self._math_func("max", ["total"])
            elif self.series.math == "median_count_per_actor":
                math_func = self._math_quantile(0.5, ["total"])
            elif self.series.math == "p75_count_per_actor":
                math_func = self._math_quantile(0.75, ["total"])
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
                    "inner_query": create_placeholder("events_query"),
                    "total_alias": total_alias,
                },
            )
            assert isinstance(query, ast.SelectQuery)

            if not self.is_total_value:
                query.select.append(ast.Field(chain=["day_start"]))
                query.group_by = [ast.Field(chain=["day_start"])]

            return query

        # For a given label, WAU is calculated as the 7 days leading up to the time on that label, non inclusive of that label.
        # For example, hourly WAU for 2024/03/10 06:00:00 shows events with 2024/03/03 06:00:00 <= timestamp < 2024/03/10 06:00:00
        # MAU is the same but for 30 days
        query = parse_select(
            """
                SELECT
                    d.timestamp,
                    COUNT(DISTINCT actor_id) AS counts
                FROM {cross_join_select_query} e
                CROSS JOIN (
                    SELECT
                        {date_to_start_of_interval} - {number_interval_period} AS timestamp
                    FROM
                        numbers(dateDiff({interval}, {date_from_start_of_interval} - {inclusive_lookback}, {date_to}))
                ) d
                WHERE
                    e.timestamp <= d.timestamp AND
                    e.timestamp > d.timestamp - {inclusive_lookback}
                GROUP BY d.timestamp
                ORDER BY d.timestamp
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                **self._interval_placeholders(),
                "cross_join_select_query": create_placeholder("events_query"),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        assert isinstance(query.group_by, list)

        if self.is_total_value:
            query.select = [ast.Field(chain=["d", "timestamp"]), ast.Field(chain=["actor_id"])]
            query.group_by.append(ast.Field(chain=["actor_id"]))

        return query

    def _actors_events_query(
        self, events_where_clause: ast.Expr, sample_value: ast.RatioExpr
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        date_from_with_lookback = "{date_from} - {inclusive_lookback}"
        if self.chart_display_type in NON_TIME_SERIES_DISPLAY_TYPES and self.series.math in (
            BaseMathType.WEEKLY_ACTIVE,
            BaseMathType.MONTHLY_ACTIVE,
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
                    name=self._interval_function_name,
                    args=[ast.Field(chain=["timestamp"])],
                ),
            )

            query = parse_select(
                (
                    """
                    SELECT
                        count() AS total
                    FROM {table} AS e
                    WHERE {events_where_clause}
                    GROUP BY {person_field}
                """
                    if isinstance(self.series, DataWarehouseNode)
                    else """
                    SELECT
                        count() AS total
                    FROM events AS e
                    SAMPLE {sample}
                    WHERE {events_where_clause}
                    GROUP BY {person_field}
                """
                ),
                placeholders={
                    "table": self._table_expr,
                    "events_where_clause": where_clause_combined,
                    "sample": sample_value,
                    "person_field": self.person_field,
                },
            )
            assert isinstance(query, ast.SelectQuery)
            assert isinstance(query.group_by, list)

            if not self.is_total_value:
                query.select.append(day_start)
                query.group_by.append(ast.Field(chain=["day_start"]))

            return query

        if self.query_date_range.interval_name == "hour":
            timestamp_expr = "toStartOfHour(timestamp) AS timestamp"
        elif self.query_date_range.interval_name == "minute":
            timestamp_expr = "toStartOfMinute(timestamp) AS timestamp"
        else:
            timestamp_expr = "toStartOfDay(timestamp) AS timestamp"

        return parse_select(
            f"""
                SELECT
                    {timestamp_expr},
                    {{person_field}} AS actor_id
                FROM
                    events e
                SAMPLE {{sample}}
                WHERE {{events_where_clause}}
                GROUP BY
                    timestamp,
                    actor_id
            """,
            placeholders={
                "events_where_clause": where_clause_combined,
                "sample": sample_value,
                "person_field": self.person_field,
            },
        )

    def get_actors_query_orchestrator(self, events_where_clause: ast.Expr, sample_value: ast.RatioExpr):
        events_query = cast(ast.SelectQuery, self._actors_events_query(events_where_clause, sample_value))
        inner_select = cast(ast.SelectQuery, self._actors_inner_select_query())
        parent_select = cast(ast.SelectQuery, self._actors_parent_select_query())

        class QueryOrchestrator:
            events_query_builder: QueryAlternator
            inner_select_query_builder: QueryAlternator
            parent_select_query_builder: QueryAlternator

            def __init__(self):
                self.events_query_builder = QueryAlternator(events_query)
                self.inner_select_query_builder = QueryAlternator(inner_select)
                self.parent_select_query_builder = QueryAlternator(parent_select)

            def build(self):
                events_query = self.events_query_builder.build()
                inner_query = replace_placeholders(
                    self.inner_select_query_builder.build(), {"events_query": events_query}
                )
                return replace_placeholders(self.parent_select_query_builder.build(), {"inner_query": inner_query})

        return QueryOrchestrator()

    def _first_time_parent_query(self):
        aggregation_type = self.select_aggregation()
        query = ast.SelectQuery(
            select=[
                ast.Alias(expr=aggregation_type, alias="total"),
            ],
            select_from=ast.JoinExpr(table=create_placeholder("events_query")),
        )
        query.group_by = []

        if not self.is_total_value:
            query.select.append(
                ast.Alias(
                    expr=ast.Call(
                        name=self._interval_function_name,
                        args=[ast.Field(chain=["min_timestamp"])],
                    ),
                    alias="day_start",
                )
            )
            query.group_by.append(ast.Field(chain=["day_start"]))

        return query

    def get_first_time_math_query_orchestrator(
        self,
        events_where_clause: ast.Expr,
        sample_value: ast.RatioExpr,
        event_name_filter: ast.Expr | None = None,
    ):
        date_placeholders = self.query_date_range.to_placeholders()
        date_from = parse_expr(
            "timestamp >= {date_from_with_adjusted_start_of_interval}",
            placeholders=date_placeholders,
        )
        date_to = parse_expr(
            "timestamp <= {date_to}",
            placeholders=date_placeholders,
        )

        events_query = ast.SelectQuery(select=[])
        parent_select = self._first_time_parent_query()
        is_first_matching_event = self.is_first_matching_event()

        class QueryOrchestrator:
            events_query_builder: FirstTimeForUserEventsQueryAlternator
            parent_query_builder: QueryAlternator

            def __init__(self):
                self.events_query_builder = FirstTimeForUserEventsQueryAlternator(
                    events_query,
                    date_from,
                    date_to,
                    filters=events_where_clause,
                    event_or_action_filter=event_name_filter,
                    ratio=sample_value,
                    is_first_matching_event=is_first_matching_event,
                )
                self.parent_query_builder = QueryAlternator(parent_select)

            def build(self):
                events_query = self.events_query_builder.build()
                return replace_placeholders(self.parent_query_builder.build(), {"events_query": events_query})

        return QueryOrchestrator()
