from posthog.schema import CalendarHeatmapQuery, ResolvedDateRangeResponse, TrendsQueryResponse

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner


class CalendarHeatmapTrendsQueryRunner(TrendsQueryRunner):
    """
    A wrapper around TrendsQueryRunner that delegates to CalendarHeatmapQueryRunner
    but returns the response in TrendsQueryResponse format for frontend compatibility.

    This ensures that calendar heatmap queries return data in the format expected by
    the frontend (with calendar_heatmap_data in the trends response).
    """

    def _calculate(self):
        from posthog.hogql_queries.insights.trends.calendar_heatmap_query_runner import CalendarHeatmapQueryRunner

        # Convert TrendsQuery to CalendarHeatmapQuery
        calendar_query = CalendarHeatmapQuery(
            dateRange=self.query.dateRange,
            filterTestAccounts=self.query.filterTestAccounts,
            properties=self.query.properties,
            series=self.query.series,
            conversionGoal=getattr(self.query, "conversionGoal", None),
        )

        # Create and run calendar heatmap query runner
        calendar_runner = CalendarHeatmapQueryRunner(
            query=calendar_query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        calendar_response = calendar_runner._calculate()

        # Convert calendar response to trends response format
        return TrendsQueryResponse(
            results=[
                {
                    "action": {
                        "id": self.series_event(self.query.series[0]) if self.query.series else "heatmap",
                        "type": "events",
                        "order": 0,
                        "name": self.series_event(self.query.series[0]) if self.query.series else "Heatmap",
                        "math": self.query.series[0].math if self.query.series else "total",
                    },
                    "label": self.series_event(self.query.series[0]) if self.query.series else "Heatmap",
                    "data": [],  # Empty array for non-time-series data
                    "aggregated_value": calendar_response.results.allAggregations,
                    "calendar_heatmap_data": calendar_response.results,  # Store the original heatmap data
                    "count": calendar_response.results.allAggregations,
                }
            ],
            timings=calendar_response.timings,
            hogql=calendar_response.hogql,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )
