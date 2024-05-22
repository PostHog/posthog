from typing import Optional, Union, Any
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext, get_breakdown_limit_for_context, BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.placeholders import replace_placeholders, find_placeholders
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.trends.aggregation_operations import AggregationOperations
from posthog.hogql_queries.insights.trends.utils import get_properties_chain
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team
from posthog.schema import (
    BreakdownFilter,
    BreakdownType,
    ChartDisplayType,
    ActionsNode,
    EventsNode,
    DataWarehouseNode,
    HogQLQueryModifiers,
)
from functools import cached_property

BREAKDOWN_OTHER_STRING_LABEL = "$$_posthog_breakdown_other_$$"
BREAKDOWN_OTHER_NUMERIC_LABEL = 9007199254740991  # pow(2, 53) - 1, for JS compatibility
BREAKDOWN_OTHER_DISPLAY = "Other (i.e. all remaining values)"
BREAKDOWN_NULL_STRING_LABEL = "$$_posthog_breakdown_null_$$"
BREAKDOWN_NULL_NUMERIC_LABEL = 9007199254740990  # pow(2, 53) - 2, for JS compatibility
BREAKDOWN_NULL_DISPLAY = "None (i.e. no value)"


class BreakdownValues:
    team: Team
    series: Union[EventsNode, ActionsNode, DataWarehouseNode]
    breakdown_field: Union[str, float, list[Union[str, float]]]
    breakdown_type: BreakdownType
    events_filter: ast.Expr
    chart_display_type: ChartDisplayType
    histogram_bin_count: Optional[int]
    group_type_index: Optional[int]
    hide_other_aggregation: Optional[bool]
    normalize_url: Optional[bool]
    breakdown_limit: int
    query_date_range: QueryDateRange
    modifiers: HogQLQueryModifiers
    limit_context: LimitContext

    def __init__(
        self,
        team: Team,
        series: Union[EventsNode, ActionsNode, DataWarehouseNode],
        events_filter: ast.Expr,
        chart_display_type: ChartDisplayType,
        breakdown_filter: BreakdownFilter,
        query_date_range: QueryDateRange,
        modifiers: HogQLQueryModifiers,
        limit_context: LimitContext = LimitContext.QUERY,
    ):
        self.team = team
        self.series = series
        self.breakdown_field = breakdown_filter.breakdown  # type: ignore
        self.breakdown_type = breakdown_filter.breakdown_type  # type: ignore
        self.events_filter = events_filter
        self.chart_display_type = chart_display_type
        self.histogram_bin_count = (
            int(breakdown_filter.breakdown_histogram_bin_count)
            if breakdown_filter.breakdown_histogram_bin_count is not None
            else None
        )
        self.group_type_index = (
            int(breakdown_filter.breakdown_group_type_index)
            if breakdown_filter.breakdown_group_type_index is not None
            else None
        )
        self.hide_other_aggregation = breakdown_filter.breakdown_hide_other_aggregation
        self.normalize_url = breakdown_filter.breakdown_normalize_url
        self.breakdown_limit = breakdown_filter.breakdown_limit or get_breakdown_limit_for_context(limit_context)
        self.query_date_range = query_date_range
        self.modifiers = modifiers
        self.limit_context = limit_context

    def get_breakdown_values(self) -> list[str | int]:
        if self.breakdown_type == "cohort":
            if self.breakdown_field == "all":
                return [0]

            if isinstance(self.breakdown_field, list):
                return [value if isinstance(value, str) else int(value) for value in self.breakdown_field]

            return [self.breakdown_field if isinstance(self.breakdown_field, str) else int(self.breakdown_field)]

        if self.breakdown_type == "hogql":
            select_field = ast.Alias(
                alias="value",
                expr=parse_expr(str(self.breakdown_field)),
            )
        else:
            select_field = ast.Alias(
                alias="value",
                expr=ast.Field(
                    chain=get_properties_chain(
                        breakdown_type=self.breakdown_type,
                        breakdown_field=str(self.breakdown_field),
                        group_type_index=self.group_type_index,
                    )
                ),
            )

        if not self.histogram_bin_count:
            if self.normalize_url:
                select_field.expr = parse_expr(
                    "empty(trimRight({node}, '/?#')) ? '/' : trimRight({node}, '/?#')",
                    placeholders={"node": select_field.expr},
                )

            select_field.expr = ast.Call(name="toString", args=[select_field.expr])

        if self.chart_display_type == ChartDisplayType.WorldMap:
            breakdown_limit = BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES
        else:
            breakdown_limit = int(self.breakdown_limit)

        aggregation_expression: ast.Expr
        if self._aggregation_operation.aggregating_on_session_duration():
            aggregation_expression = ast.Call(name="max", args=[ast.Field(chain=["session", "$session_duration"])])
        elif self.series.math == "dau":
            # When aggregating by (daily) unique users, run the breakdown aggregation on count(e.uuid).
            # This retains legacy compatibility and should be removed once we have the new trends in production.
            aggregation_expression = parse_expr("count({id_field})", placeholders={"id_field": self._id_field})
        else:
            aggregation_expression = self._aggregation_operation.select_aggregation()
            # Take a shortcut with WAU and MAU queries. Get the total AU-s for the period instead.
            if "replaced" in find_placeholders(aggregation_expression):
                actor = "e.distinct_id" if self.team.aggregate_users_by_distinct_id else "e.person_id"
                replaced = parse_expr(f"count(DISTINCT {actor})")
                aggregation_expression = replace_placeholders(aggregation_expression, {"replaced": replaced})

        timestamp_field = self.series.timestamp_field if hasattr(self.series, "timestamp_field") else "timestamp"
        date_filter = ast.And(
            exprs=[
                parse_expr(
                    "{timestamp} >= {date_from_with_adjusted_start_of_interval}",
                    placeholders={
                        **self.query_date_range.to_placeholders(),
                        "timestamp": ast.Field(chain=[timestamp_field]),
                    },
                ),
                parse_expr(
                    "{timestamp} <= {date_to}",
                    placeholders={
                        **self.query_date_range.to_placeholders(),
                        "timestamp": ast.Field(chain=[timestamp_field]),
                    },
                ),
            ]
        )

        inner_events_query = parse_select(
            """
                SELECT
                    {select_field},
                    {aggregation_expression} as count
                FROM {table} e
                WHERE
                    {date_filter} and {events_where}
                GROUP BY
                    value
                ORDER BY
                    count DESC,
                    value DESC
                LIMIT {breakdown_limit_plus_one}
            """,
            placeholders={
                "select_field": select_field,
                "aggregation_expression": aggregation_expression,
                "table": self._table,
                "date_filter": date_filter,
                "events_where": self.events_filter,
                "breakdown_limit_plus_one": ast.Constant(value=breakdown_limit + 1),
            },
        )

        # Reverse the order if looking at the smallest values
        if self.series.math_property is not None and self.series.math == "min":
            if (
                isinstance(inner_events_query, ast.SelectQuery)
                and inner_events_query.order_by is not None
                and isinstance(inner_events_query.order_by[0], ast.OrderExpr)
            ):
                inner_events_query.order_by[0].order = "ASC"

        values: list[Any]
        if self.histogram_bin_count is not None:
            query = parse_select(
                """
                    SELECT {expr} FROM ({inner_events_query})
                """,
                placeholders={
                    "inner_events_query": inner_events_query,
                    "expr": self._to_bucketing_expression(),
                },
            )
            response = execute_hogql_query(
                query_type="TrendsQueryBreakdownValues",
                query=query,
                team=self.team,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )
            if response.results and len(response.results) > 0:
                values = response.results[0][0]
            else:
                values = []
        else:
            # We're not running this through groupArray, as that eats NULL values.
            query = inner_events_query
            response = execute_hogql_query(
                query_type="TrendsQueryBreakdownValues",
                query=query,
                team=self.team,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )
            value_index = (response.columns or []).index("value")
            values = [row[value_index] for row in response.results or []]

            needs_other = False
            if len(values) == breakdown_limit + 1:
                needs_other = True
                values = values[:-1]

            # Add "other" value if "other" is not hidden and we're not bucketing numeric values
            if self.hide_other_aggregation is not True and self.histogram_bin_count is None:
                values = [BREAKDOWN_NULL_STRING_LABEL if value in (None, "") else value for value in values]
                if needs_other:
                    values = [BREAKDOWN_OTHER_STRING_LABEL, *values]

        if len(values) == 0:
            values.insert(0, None)
            return values

        return values

    def _to_bucketing_expression(self) -> ast.Expr:
        assert isinstance(self.histogram_bin_count, int)

        if self.histogram_bin_count <= 1:
            qunatile_expression = "quantiles(0,1)(value)"
        else:
            quantiles = []
            bin_size = 1.0 / self.histogram_bin_count
            for i in range(self.histogram_bin_count + 1):
                quantiles.append(i * bin_size)

            qunatile_expression = f"quantiles({','.join([f'{quantile:.2f}' for quantile in quantiles])})(value)"

        return parse_expr(f"arrayCompact(arrayMap(x -> floor(x, 2), {qunatile_expression}))")

    @cached_property
    def _id_field(self) -> ast.Field:
        if isinstance(self.series, DataWarehouseNode):
            return ast.Field(chain=["e", self.series.id_field])

        return ast.Field(chain=["e", "uuid"])

    @cached_property
    def _table(self) -> ast.Field:
        if isinstance(self.series, DataWarehouseNode):
            return ast.Field(chain=[self.series.table_name])

        return ast.Field(chain=["events"])

    @cached_property
    def _aggregation_operation(self) -> AggregationOperations:
        return AggregationOperations(
            self.team,
            self.series,
            self.chart_display_type,
            self.query_date_range,
            is_total_value=True,  # doesn't matter in this case
        )
