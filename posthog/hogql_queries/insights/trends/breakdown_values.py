from typing import List, Optional, Union, Any
from posthog.constants import BREAKDOWN_VALUES_LIMIT, BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.trends.utils import get_properties_chain
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team
from posthog.schema import ChartDisplayType


class BreakdownValues:
    team: Team
    event_name: str
    breakdown_field: Union[str, float]
    breakdown_type: str
    query_date_range: QueryDateRange
    events_filter: ast.Expr
    chart_display_type: ChartDisplayType
    histogram_bin_count: Optional[int]
    group_type_index: Optional[int]

    def __init__(
        self,
        team: Team,
        event_name: str,
        breakdown_field: Union[str, float],
        query_date_range: QueryDateRange,
        breakdown_type: str,
        events_filter: ast.Expr,
        chart_display_type: ChartDisplayType,
        histogram_bin_count: Optional[float] = None,
        group_type_index: Optional[float] = None,
    ):
        self.team = team
        self.event_name = event_name
        self.breakdown_field = breakdown_field
        self.query_date_range = query_date_range
        self.breakdown_type = breakdown_type
        self.events_filter = events_filter
        self.chart_display_type = chart_display_type
        self.histogram_bin_count = int(histogram_bin_count) if histogram_bin_count is not None else None
        self.group_type_index = int(group_type_index) if group_type_index is not None else None

    def get_breakdown_values(self) -> List[str | int]:
        if self.breakdown_type == "cohort":
            if self.breakdown_field == "all":
                return [0]

            return [int(self.breakdown_field)]

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
                        breakdown_field=self.breakdown_field,
                        group_type_index=self.group_type_index,
                    )
                ),
            )

        inner_events_query = parse_select(
            """
                SELECT
                    {select_field},
                    count(e.uuid) as count
                FROM
                    events e
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
                "breakdown_limit": ast.Constant(
                    value=BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES
                    if self.chart_display_type == ChartDisplayType.WorldMap
                    else BREAKDOWN_VALUES_LIMIT
                ),
            },
        )

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

        if self.histogram_bin_count is None:
            values.insert(0, None)

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
