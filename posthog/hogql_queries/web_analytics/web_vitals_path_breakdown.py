from posthog.schema import (
    CachedWebStatsTableQueryResponse,
    WebVitalsMetricBand,
    WebVitalsPathBreakdownQuery,
    WebVitalsPathBreakdownQueryResponse,
    WebVitalsPathBreakdownResult,
    WebVitalsPathBreakdownResultItem,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import get_property_type, property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.queries.trends.util import PROPERTY_MATH_FUNCTIONS


class WebVitalsPathBreakdownQueryRunner(WebAnalyticsQueryRunner[WebVitalsPathBreakdownQueryResponse]):
    query: WebVitalsPathBreakdownQuery
    cached_response: CachedWebStatsTableQueryResponse

    def to_query(self):
        return parse_select(
            """
SELECT * FROM (
    SELECT multiIf(
        value <= {good_threshold}, 'good',
        value <= {needs_improvements_threshold}, 'needs_improvements',
        'poor'
    ) AS band,
    path,
    value
    FROM {inner_query}
)
ORDER BY value ASC, path ASC
LIMIT 20 BY band
""",
            timings=self.timings,
            placeholders={
                "inner_query": self._inner_query(),
                "good_threshold": ast.Constant(value=self.query.thresholds[0]),
                "needs_improvements_threshold": ast.Constant(value=self.query.thresholds[1]),
            },
        )

    # NOTE: Hardcoded to return at most 20 results per band, but we can change that if needed
    def _inner_query(self):
        return parse_select(
            """
SELECT
    {breakdown_by} AS path,
    {percentile} AS value
FROM events
WHERE and(event == '$web_vitals', path IS NOT NULL, {inside_periods_expr}, {event_properties_expr})
GROUP BY path
HAVING value >= 0
            """,
            timings=self.timings,
            placeholders={
                "breakdown_by": self._apply_path_cleaning(ast.Field(chain=["events", "properties", "$pathname"])),
                "percentile": self._percentile_expr(),
                "inside_periods_expr": self._periods_expression(),
                "event_properties_expr": self._event_properties(),
            },
        )

    def _event_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) in ["event", "person"]
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def _percentile_expr(self) -> ast.Expr:
        percentile_function = PROPERTY_MATH_FUNCTIONS[self.query.percentile]
        metric_value_field = f"properties.$web_vitals_{self.query.metric.value}_value"

        return parse_expr(f"{percentile_function}(toFloat({metric_value_field}))")

    def _calculate(self):
        query = self.to_query()
        response = execute_hogql_query(
            query_type="web_vitals_path_breakdown_query",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        assert response.results is not None

        # Return a list because Pydantic is boring, but it will always be a single entry
        return WebVitalsPathBreakdownQueryResponse(
            results=[
                WebVitalsPathBreakdownResult(
                    good=self._get_results_for_band(response.results, WebVitalsMetricBand.GOOD),
                    needs_improvements=self._get_results_for_band(
                        response.results, WebVitalsMetricBand.NEEDS_IMPROVEMENTS
                    ),
                    poor=self._get_results_for_band(response.results, WebVitalsMetricBand.POOR),
                )
            ],
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )

    def _get_results_for_band(
        self, results: list[tuple[str, str, float]], band: WebVitalsMetricBand
    ) -> list[WebVitalsPathBreakdownResultItem]:
        return [WebVitalsPathBreakdownResultItem(path=row[1], value=row[2]) for row in results if row[0] == band.value]
