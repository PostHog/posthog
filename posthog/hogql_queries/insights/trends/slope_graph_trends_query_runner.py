from posthog.schema import ChartDisplayType, TrendsFilter, TrendsQueryResponse

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner


def _collapse_to_endpoints(result: dict) -> None:
    """Keep only the first and last bucket of a trends series — the slope's two points."""
    for key in ("data", "labels", "days"):
        values = result.get(key)
        if isinstance(values, list) and len(values) > 2:
            result[key] = [values[0], values[-1]]


class SlopeGraphTrendsQueryRunner(TrendsQueryRunner):
    """Renders the change between the first and last interval bucket of the selected range.

    A slope shows two points: the value of the first group and the value of the last group, at the
    chosen interval (day/week/month). It runs the ordinary trends time series once — the interval
    already returns one value per bucket in a single query, with every math type, breakdown and
    filter handled — then keeps only the first and last bucket of each series. A range spanning a
    single bucket yields a one-point series, which the frontend drops (there's no slope to draw).
    The last bucket is shown as-is even when it is the current, still-accumulating period; the
    frontend dashes that endpoint, mirroring the line chart. Because it has its own display type it
    caches under its own key rather than sharing the line graph's result.
    """

    def _calculate(self) -> TrendsQueryResponse:
        series_query = self.query.model_copy(deep=True)
        # The two ends *are* the comparison — don't also overlay the prior period.
        series_query.compareFilter = None
        if series_query.trendsFilter is None:
            series_query.trendsFilter = TrendsFilter()
        # Compute the full interval series in one query; we slice it to its ends below.
        series_query.trendsFilter.display = ChartDisplayType.ACTIONS_LINE_GRAPH

        response = TrendsQueryRunner(
            query=series_query,
            team=self.team,
            timings=self.timings,
            limit_context=self.limit_context,
            modifiers=self.modifiers,
            user=self.user,
        ).calculate()

        for result in response.results or []:
            _collapse_to_endpoints(result)
        return response
