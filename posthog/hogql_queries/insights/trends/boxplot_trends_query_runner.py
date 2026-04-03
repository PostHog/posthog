from posthog.schema import (
    BoxPlotDatum,
    ChartDisplayType,
    DataWarehouseNode,
    QueryTiming,
    ResolvedDateRangeResponse,
    TrendsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.trends.aggregation_operations import AggregationOperations
from posthog.hogql_queries.insights.trends.trends_query_builder import TrendsQueryBuilder
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.insights.utils.utils import get_response_hogql
from posthog.hogql_queries.utils.timestamp_utils import format_label_date


class BoxPlotTrendsQueryRunner(TrendsQueryRunner):
    def _calculate(self):
        resolved_date_range = ResolvedDateRangeResponse(
            date_from=self.query_date_range.date_from(),
            date_to=self.query_date_range.date_to(),
        )

        if not self.query.series:
            return TrendsQueryResponse(
                results=[],
                boxplot_data=[],
                modifiers=self.modifiers,
                resolved_date_range=resolved_date_range,
            )

        if any(not s.math_property for s in self.query.series):
            return TrendsQueryResponse(
                results=[],
                boxplot_data=[],
                modifiers=self.modifiers,
                error="A numeric property must be selected for box plot.",
                resolved_date_range=resolved_date_range,
            )

        includes_time = self.query_date_range.interval_name in ("hour", "minute")
        day_format = "%Y-%m-%d %H:%M:%S" if includes_time else "%Y-%m-%d"

        series_queries: list[tuple[int, str, ast.SelectQuery]] = []

        for series_index, series_node in enumerate(self.query.series):
            series_label = self._get_series_label(series_node, series_index)

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

            if agg_ops.aggregating_on_session_property():
                boxplot_query = self._build_session_property_query(
                    query_builder, agg_ops, series_node, events_filter, day_start
                )
            elif getattr(series_node, "math_property_type", None) == "session_properties":
                return TrendsQueryResponse(
                    results=[],
                    boxplot_data=[],
                    modifiers=self.modifiers,
                    error=f"Unsupported session property: {series_node.math_property}",
                    resolved_date_range=resolved_date_range,
                )
            else:
                boxplot_query = self._build_standard_query(
                    query_builder, agg_ops, series_node, events_filter, day_start
                )

            series_queries.append((series_index, series_label, boxplot_query))

        response_hogql = get_response_hogql(
            [q for _, _, q in series_queries],
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )

        all_boxplot_data: list[BoxPlotDatum] = []
        all_timings: list[QueryTiming] = []
        debug_errors: list[str] = []

        for series_index, series_label, boxplot_query in series_queries:
            response = execute_hogql_query(
                query_type="BoxPlotTrendsQuery",
                query=boxplot_query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

            if response.timings is not None:
                all_timings.extend(response.timings)
            if response.error:
                debug_errors.append(response.error)

            results_by_day: dict[str, BoxPlotDatum] = {}
            for row in response.results or []:
                day_val = row[0]
                key = day_val.strftime(day_format)
                results_by_day[key] = BoxPlotDatum(
                    day=key,
                    label=format_label_date(day_val, self.query_date_range, self.team.week_start_day),
                    min=float(row[1]) if row[1] is not None else 0.0,
                    p25=float(row[2]) if row[2] is not None else 0.0,
                    median=float(row[3]) if row[3] is not None else 0.0,
                    p75=float(row[4]) if row[4] is not None else 0.0,
                    max=float(row[5]) if row[5] is not None else 0.0,
                    mean=float(row[6]) if row[6] is not None else 0.0,
                    series_index=series_index,
                    series_label=series_label,
                )

            for dt in self.query_date_range.all_values():
                key = dt.strftime(day_format)
                if key in results_by_day:
                    all_boxplot_data.append(results_by_day[key])
                else:
                    all_boxplot_data.append(
                        BoxPlotDatum(
                            day=key,
                            label=format_label_date(dt, self.query_date_range, self.team.week_start_day),
                            min=0.0,
                            p25=0.0,
                            median=0.0,
                            p75=0.0,
                            max=0.0,
                            mean=0.0,
                            series_index=series_index,
                            series_label=series_label,
                        )
                    )

        return TrendsQueryResponse(
            results=[],
            boxplot_data=all_boxplot_data,
            timings=all_timings or None,
            hogql=response_hogql,
            error=". ".join(debug_errors) if debug_errors else None,
            modifiers=self.modifiers,
            resolved_date_range=resolved_date_range,
        )

    def _get_series_label(self, series_node, series_index: int) -> str:
        try:
            event_name = self.series_event(series_node)
        except Exception:
            event_name = None
        base_label = event_name or "All events"
        if series_node.custom_name:
            base_label = series_node.custom_name
        prop = series_node.math_property or ""
        return f"{base_label} - {prop}" if prop else base_label

    @staticmethod
    def _boxplot_stats_select(field_expr: ast.Expr) -> list[ast.Expr]:
        return [
            ast.Alias(alias="min_val", expr=ast.Call(name="min", args=[field_expr])),
            ast.Alias(
                alias="p25",
                expr=ast.Call(name="quantile", params=[ast.Constant(value=0.25)], args=[field_expr]),
            ),
            ast.Alias(
                alias="median_val",
                expr=ast.Call(name="quantile", params=[ast.Constant(value=0.5)], args=[field_expr]),
            ),
            ast.Alias(
                alias="p75",
                expr=ast.Call(name="quantile", params=[ast.Constant(value=0.75)], args=[field_expr]),
            ),
            ast.Alias(alias="max_val", expr=ast.Call(name="max", args=[field_expr])),
            ast.Alias(alias="mean_val", expr=ast.Call(name="avg", args=[field_expr])),
        ]

    def _build_standard_query(self, query_builder, agg_ops, series_node, events_filter, day_start) -> ast.SelectQuery:
        chain = agg_ops._get_math_chain()
        field_expr = ast.Call(name="toFloat", args=[ast.Field(chain=chain)])

        return ast.SelectQuery(
            select=[day_start, *self._boxplot_stats_select(field_expr)],
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

    def _build_session_property_query(
        self, query_builder, agg_ops, series_node, events_filter, day_start
    ) -> ast.SelectQuery:
        session_property_select = query_builder._get_session_property_select_expr()
        chain = agg_ops._get_math_chain()

        inner_query = ast.SelectQuery(
            select=[day_start, *session_property_select],
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
            group_by=[ast.Field(chain=["$session_id"]), ast.Field(chain=["day_start"])],
        )

        field_expr = ast.Call(name="toFloat", args=[ast.Field(chain=chain)])

        return ast.SelectQuery(
            select=[ast.Field(chain=["day_start"]), *self._boxplot_stats_select(field_expr)],
            select_from=ast.JoinExpr(table=inner_query),
            group_by=[ast.Field(chain=["day_start"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["day_start"]), order="ASC")],
        )
