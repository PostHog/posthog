from posthog.hogql import ast
from posthog.hogql.parser import (
    parse_select,
    parse_expr,
)

from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.schema import (
    CachedWebStatsTableQueryResponse,
    CoreWebVitalsPathBreakdownQuery,
    CoreWebVitalsPathBreakdownQueryResponse,
    CoreWebVitalsPathBreakdownResult,
    CoreWebVitalsPathBreakdownResultItem,
    CoreWebVitalsMetricBand,
)
from posthog.hogql.property import (
    property_to_expr,
    get_property_type,
)
from posthog.queries.trends.util import PROPERTY_MATH_FUNCTIONS


class CoreWebVitalsPathBreakdownQueryRunner(WebAnalyticsQueryRunner):
    query: CoreWebVitalsPathBreakdownQuery
    response: CoreWebVitalsPathBreakdownQueryResponse
    cached_response: CachedWebStatsTableQueryResponse

    def to_query(self):
        return parse_select(
            "SELECT * FROM {good_query} UNION ALL {needs_improvements_query} UNION ALL {poor_query}",
            timings=self.timings,
            placeholders={
                "good_query": self._select_by_band(CoreWebVitalsMetricBand.GOOD),
                "needs_improvements_query": self._select_by_band(CoreWebVitalsMetricBand.NEEDS_IMPROVEMENTS),
                "poor_query": self._select_by_band(CoreWebVitalsMetricBand.POOR),
            },
        )

    # KLUDGE: There's a hack here to get around the fact that we can't return an empty result from this
    # subquery or else Clickhouse will be very sad and throw an error along these lines:
    # `Scalar subquery returned empty result of type Tuple(String, Nullable(String), Nullable(Float64)) which cannot be Nullable.`
    #
    # NOTE: Hardcoded to return at most 20 results per band, but we can change that if needed
    def _select_by_band(self, band: CoreWebVitalsMetricBand):
        return parse_select(
            """
SELECT band, path, value FROM (
    SELECT
        {band} AS band,
        {breakdown_by} AS path,
        {percentile} AS value
    FROM events
    WHERE and(event == '$web_vitals', path IS NOT NULL, {inside_periods_expr}, {event_properties_expr})
    GROUP BY path
    HAVING {thresholds_expr}
    ORDER BY value ASC, path ASC
    LIMIT 20
) UNION ALL (
    SELECT 'dummy' AS band, 'dummy' AS path, 0 AS value
)
            """,
            timings=self.timings,
            placeholders={
                "band": ast.Constant(value=band.value),
                "breakdown_by": self._apply_path_cleaning(ast.Field(chain=["events", "properties", "$pathname"])),
                "percentile": self._percentile_expr(),
                "inside_periods_expr": self._periods_expression(),
                "event_properties_expr": self._event_properties(),
                "thresholds_expr": self._thresholds_for_band(band),
            },
        )

    def _thresholds_for_band(self, band: CoreWebVitalsMetricBand) -> ast.Expr:
        thresholds = {
            CoreWebVitalsMetricBand.GOOD: (-1, self.query.thresholds[0]),
            CoreWebVitalsMetricBand.NEEDS_IMPROVEMENTS: (self.query.thresholds[0], self.query.thresholds[1]),
            CoreWebVitalsMetricBand.POOR: (
                self.query.thresholds[1],
                100_000_000,
            ),  # Virtually infinity for the purposes of this query
        }

        threshold = thresholds[band]
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=ast.Field(chain=["value"]),
                    right=ast.Constant(value=threshold[0]),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["value"]),
                    right=ast.Constant(value=threshold[1]),
                ),
            ]
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

    def calculate(self):
        query = self.to_query()
        response = execute_hogql_query(
            query_type="core_web_vitals_path_breakdown_query",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        assert response.results

        # Return a list because Pydantic is boring, but it will always be a single entry
        return CoreWebVitalsPathBreakdownQueryResponse(
            results=[
                CoreWebVitalsPathBreakdownResult(
                    good=self._get_results_for_band(response.results, CoreWebVitalsMetricBand.GOOD),
                    needs_improvements=self._get_results_for_band(
                        response.results, CoreWebVitalsMetricBand.NEEDS_IMPROVEMENTS
                    ),
                    poor=self._get_results_for_band(response.results, CoreWebVitalsMetricBand.POOR),
                )
            ],
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )

    def _get_results_for_band(
        self, results: list[tuple[str, str, float]], band: CoreWebVitalsMetricBand
    ) -> list[CoreWebVitalsPathBreakdownResultItem]:
        return [
            CoreWebVitalsPathBreakdownResultItem(path=row[1], value=row[2]) for row in results if row[0] == band.value
        ]
