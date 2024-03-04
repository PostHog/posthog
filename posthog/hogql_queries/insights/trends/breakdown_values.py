from typing import List, Optional, Union, Any
from posthog.constants import BREAKDOWN_VALUES_LIMIT, BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.placeholders import replace_placeholders
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.trends.aggregation_operations import AggregationOperations
from posthog.hogql_queries.insights.trends.utils import get_properties_chain
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team
from posthog.schema import BreakdownFilter, BreakdownType, ChartDisplayType, ActionsNode, EventsNode, DataWarehouseNode
from functools import cached_property

BREAKDOWN_OTHER_STRING_LABEL = "$$_posthog_breakdown_other_$$"
BREAKDOWN_OTHER_NUMERIC_LABEL = 9007199254740991  # pow(2, 53) - 1, for JS compatibility
BREAKDOWN_NULL_STRING_LABEL = "$$_posthog_breakdown_null_$$"
BREAKDOWN_NULL_NUMERIC_LABEL = 9007199254740990  # pow(2, 53) - 2, for JS compatibility


class BreakdownValues:
    team: Team
    series: Union[EventsNode, ActionsNode, DataWarehouseNode]
    breakdown_field: Union[str, float, List[Union[str, float]]]
    breakdown_type: BreakdownType
    events_filter: ast.Expr
    chart_display_type: ChartDisplayType
    histogram_bin_count: Optional[int]
    group_type_index: Optional[int]
    hide_other_aggregation: Optional[bool]
    breakdown_limit: Optional[int]
    query_date_range: QueryDateRange

    def __init__(
        self,
        team: Team,
        series: Union[EventsNode, ActionsNode, DataWarehouseNode],
        events_filter: ast.Expr,
        chart_display_type: ChartDisplayType,
        breakdown_filter: BreakdownFilter,
        query_date_range: QueryDateRange,
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
        self.breakdown_limit = breakdown_filter.breakdown_limit
        self.query_date_range = query_date_range

    def get_breakdown_values(self) -> List[str | int]:
        if self.breakdown_type == "cohort":
            if self.breakdown_field == "all":
                return [0]

            if isinstance(self.breakdown_field, List):
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

        if self.chart_display_type == ChartDisplayType.WorldMap:
            breakdown_limit = BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES
        else:
            breakdown_limit = int(self.breakdown_limit) if self.breakdown_limit is not None else BREAKDOWN_VALUES_LIMIT

        inner_events_query = parse_select(
            """
                SELECT
                    {select_field},
                    {aggregation_expression} as count
                FROM {table} e
                WHERE
                    {events_where}
                GROUP BY
                    value
                ORDER BY
                    count DESC,
                    value DESC
                LIMIT {breakdown_limit}
            """,
            placeholders={
                "events_where": self.events_filter,
                "select_field": select_field,
                "breakdown_limit": ast.Constant(value=breakdown_limit),
                "table": self._table,
                "id_field": self._id_field,
                "aggregation_expression": replace_placeholders(
                    ast.Call(name="max", args=[ast.Field(chain=["session", "duration"])])
                    if self._aggregation_operation.aggregating_on_session_duration()
                    else self._aggregation_operation.select_aggregation(),
                    # take a shortcut with weekly_active and monthly_active options, and just select for total count
                    {"replaced": ast.Call(name="count", args=[self._id_field])},
                ),
            },
        )
        if self.series.math_property is not None and self.series.math == "min":
            if isinstance(inner_events_query, ast.SelectQuery) and isinstance(
                inner_events_query.order_by[0], ast.OrderExpr
            ):
                inner_events_query.order_by[0].order = "ASC"

        query = parse_select(
            """
                SELECT groupArray(value) FROM ({inner_events_query})
            """,
            placeholders={
                "inner_events_query": inner_events_query,
            },
        )

        if self.histogram_bin_count is not None:
            query.select = [self._to_bucketing_expression()]

        response = execute_hogql_query(
            query_type="TrendsQueryBreakdownValues",
            query=query,
            team=self.team,
        )

        values: List[Any] = response.results[0][0]

        if len(values) == 0:
            values.insert(0, None)
            return values

        # Add "other" value if "other" is not hidden and we're not bucketing numeric values
        if self.hide_other_aggregation is not True and self.histogram_bin_count is None:
            all_values_are_ints_or_none = all(isinstance(value, int) or value is None for value in values)
            all_values_are_floats_or_none = all(isinstance(value, float) or value is None for value in values)
            all_values_are_string_or_none = all(isinstance(value, str) or value is None for value in values)

            if all_values_are_ints_or_none or all_values_are_floats_or_none:
                if all_values_are_ints_or_none:
                    values = [BREAKDOWN_NULL_NUMERIC_LABEL if value is None else value for value in values]
                    values.insert(0, BREAKDOWN_OTHER_NUMERIC_LABEL)
                else:
                    values = [float(BREAKDOWN_NULL_NUMERIC_LABEL) if value is None else value for value in values]
                    values.insert(0, float(BREAKDOWN_OTHER_NUMERIC_LABEL))
            elif all_values_are_string_or_none:
                values = [BREAKDOWN_NULL_STRING_LABEL if value in (None, "") else value for value in values]
                values.insert(0, BREAKDOWN_OTHER_STRING_LABEL)

            breakdown_limit += 1  # Add one to the limit to account for the "other" value

        return values[:breakdown_limit]

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
            self.query_date_range,
            should_aggregate_values=True,  # doesn't matter in this case
        )
