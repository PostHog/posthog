from posthog.schema import (
    BoxPlotDatum,
    ChartDisplayType,
    DataWarehouseNode,
    ResolvedDateRangeResponse,
    TrendsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.trends.aggregation_operations import AggregationOperations
from posthog.hogql_queries.insights.trends.trends_query_builder import TrendsQueryBuilder
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.utils.timestamp_utils import format_label_date


class BoxPlotTrendsQueryRunner(TrendsQueryRunner):
    """
    A wrapper around TrendsQueryRunner that computes distribution statistics
    (min, q1, median, q3, max, mean) per time bucket for box plot visualizations.

    Returns TrendsQueryResponse with boxplot_data populated.
    """

    def _calculate(self):
        series_node = self.query.series[0] if self.query.series else None
        if series_node is None:
            return TrendsQueryResponse(
                results=[],
                modifiers=self.modifiers,
            )

        # Build a query that selects multiple aggregations per time bucket
        query_builder = TrendsQueryBuilder(
            trends_query=self.query,
            team=self.team,
            query_date_range=self.query_date_range,
            series=series_node,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        agg_ops = AggregationOperations(
            team=self.team,
            series=series_node,
            chart_display_type=ChartDisplayType.BOX_PLOT,
            query_date_range=self.query_date_range,
            is_total_value=False,
        )

        chain = agg_ops._get_math_chain()
        field_expr = ast.Call(name="toFloat", args=[ast.Field(chain=chain)])

        events_filter = query_builder._events_filter(
            ignore_breakdowns=False,
            breakdown=query_builder.breakdown,
        )

        day_start = ast.Alias(
            alias="day_start",
            expr=ast.Call(
                name=f"toStartOf{self.query_date_range.interval_name.title()}",
                args=[ast.Field(chain=["timestamp"])],
            ),
        )

        boxplot_query = ast.SelectQuery(
            select=[
                day_start,
                ast.Alias(alias="min_val", expr=ast.Call(name="min", args=[field_expr])),
                ast.Alias(
                    alias="q1",
                    expr=ast.Call(
                        name="quantile",
                        params=[ast.Constant(value=0.25)],
                        args=[field_expr],
                    ),
                ),
                ast.Alias(
                    alias="median_val",
                    expr=ast.Call(
                        name="quantile",
                        params=[ast.Constant(value=0.5)],
                        args=[field_expr],
                    ),
                ),
                ast.Alias(
                    alias="q3",
                    expr=ast.Call(
                        name="quantile",
                        params=[ast.Constant(value=0.75)],
                        args=[field_expr],
                    ),
                ),
                ast.Alias(alias="max_val", expr=ast.Call(name="max", args=[field_expr])),
                ast.Alias(alias="mean_val", expr=ast.Call(name="avg", args=[field_expr])),
            ],
            select_from=ast.JoinExpr(
                table=query_builder._table_expr,
                alias="e",
                sample=(
                    ast.SampleExpr(sample_value=query_builder._sample_value())
                    if not isinstance(series_node, DataWarehouseNode)
                    else None
                ),
            ),
            where=events_filter,
            group_by=[ast.Field(chain=["day_start"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["day_start"]), order="ASC")],
        )

        response = execute_hogql_query(
            query_type="BoxPlotTrendsQuery",
            query=boxplot_query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        # Build the boxplot data from query results
        boxplot_data: list[BoxPlotDatum] = []
        if response.results:
            for row in response.results:
                day_val = row[0]
                boxplot_data.append(
                    BoxPlotDatum(
                        day=day_val.strftime(
                            "%Y-%m-%d{}".format(
                                " %H:%M:%S" if self.query_date_range.interval_name in ("hour", "minute") else ""
                            )
                        ),
                        label=format_label_date(day_val, self.query_date_range, self.team.week_start_day),
                        min=float(row[1]) if row[1] is not None else 0.0,
                        q1=float(row[2]) if row[2] is not None else 0.0,
                        median=float(row[3]) if row[3] is not None else 0.0,
                        q3=float(row[4]) if row[4] is not None else 0.0,
                        max=float(row[5]) if row[5] is not None else 0.0,
                        mean=float(row[6]) if row[6] is not None else 0.0,
                    )
                )

        series_label = self.series_event(series_node) if series_node else "Box plot"

        return TrendsQueryResponse(
            results=[
                {
                    "action": {
                        "id": series_label,
                        "type": "events",
                        "order": 0,
                        "name": series_label or "All events",
                        "math": series_node.math if series_node else None,
                        "math_property": series_node.math_property if hasattr(series_node, "math_property") else None,
                    },
                    "label": series_label or "All events",
                    "data": [],
                    "count": 0,
                }
            ],
            boxplot_data=boxplot_data,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )
