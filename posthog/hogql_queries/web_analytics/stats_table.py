from posthog.schema import (
    CachedWebStatsTableQueryResponse,
    HogQLQueryModifiers,
    WebStatsBreakdown,
    WebStatsTableQuery,
    WebStatsTableQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.web_analytics.query_builders import (
    FrustrationMetricsQueryBuilder,
    MainQueryBuilder,
    PathBounceQueryBuilder,
    PathScrollBounceQueryBuilder,
)
from posthog.hogql_queries.web_analytics.query_builders.breakdown import BREAKDOWN_CONFIGS
from posthog.hogql_queries.web_analytics.stats_table_pre_aggregated import StatsTablePreAggregatedQueryBuilder
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner, map_columns

BREAKDOWN_NULL_DISPLAY = "(none)"


class WebStatsTableQueryRunner(WebAnalyticsQueryRunner[WebStatsTableQueryResponse]):
    query: WebStatsTableQuery
    cached_response: CachedWebStatsTableQueryResponse
    paginator: HogQLHasMorePaginator
    preaggregated_query_builder: StatsTablePreAggregatedQueryBuilder
    used_preaggregated_tables: bool

    def __init__(self, *args, use_v2_tables: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        # Determine table version from team property, fallback to parameter for compatibility
        team_version = getattr(self.team, "web_analytics_pre_aggregated_tables_version", None)
        self.use_v2_tables = team_version == "v2" if team_version is not None else use_v2_tables
        self.used_preaggregated_tables = False
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset if self.query.offset else None,
        )
        self.preaggregated_query_builder = StatsTablePreAggregatedQueryBuilder(self)
        self.main_query_builder = MainQueryBuilder(self)
        self.frustration_metrics_query_builder = FrustrationMetricsQueryBuilder(self)
        self.path_bounce_query_builder = PathBounceQueryBuilder(self)
        self.path_scroll_bounce_query_builder = PathScrollBounceQueryBuilder(self)

    def to_query(self) -> ast.SelectQuery:
        should_use_preaggregated = (
            self.modifiers
            and self.modifiers.useWebAnalyticsPreAggregatedTables
            and self.preaggregated_query_builder.can_use_preaggregated_tables()
        )

        if should_use_preaggregated:
            self.used_preaggregated_tables = True
            return self.preaggregated_query_builder.get_query()

        if self.query.breakdownBy == WebStatsBreakdown.PAGE:
            if self.query.conversionGoal:
                return self.main_query_builder.build(self._counts_breakdown_value())
            elif self.query.includeScrollDepth and self.query.includeBounceRate:
                return self.path_scroll_bounce_query_builder.build()
            elif self.query.includeBounceRate:
                return self.path_bounce_query_builder.build()

        if self.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE:
            if self.query.includeBounceRate:
                return self.to_entry_bounce_query()

        if self.query.breakdownBy == WebStatsBreakdown.FRUSTRATION_METRICS:
            return self.frustration_metrics_query_builder.build()

        return self.main_query_builder.build(self._counts_breakdown_value())

    def to_entry_bounce_query(self) -> ast.SelectQuery:
        return self.main_query_builder.build(self._bounce_entry_pathname_breakdown())

    def _calculate(self):
        query = self.to_query()

        # Pre-aggregated tables store data in UTC **buckets**, so we need to disable timezone conversion
        # to prevent HogQL from automatically converting DateTime fields to team timezone
        modifiers = self.modifiers
        if self.used_preaggregated_tables:
            modifiers = self.modifiers.model_copy() if self.modifiers else HogQLQueryModifiers()
            modifiers.convertToProjectTimezone = False

        response = self.paginator.execute_hogql_query(
            query_type="stats_table_query",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=modifiers,
        )
        results = self.paginator.results

        assert results is not None

        results_mapped = map_columns(
            results,
            {
                0: self._join_with_aggregation_value,  # breakdown_value
                1: lambda tuple, row: (  # Views (tuple)
                    self._unsample(tuple[0], row),
                    self._unsample(tuple[1], row),
                ),
                2: lambda tuple, row: (  # Visitors (tuple)
                    self._unsample(tuple[0], row),
                    self._unsample(tuple[1], row),
                ),
            },
        )

        columns = response.columns

        if self.query.breakdownBy == WebStatsBreakdown.LANGUAGE:
            # Keep only first 3 columns, we don't need the aggregation value in the frontend
            # Remove both the value and the column (used to generate table headers)
            results_mapped = [row[:3] for row in results_mapped]

            columns = (
                [column for column in response.columns if column != "context.columns.aggregation_value"]
                if response.columns is not None
                else response.columns
            )

        # Add cross-sell opportunity column so that the frontend can render it properly
        if columns is not None:
            if "context.columns.cross_sell" not in columns:
                columns = [*list(columns), "context.columns.cross_sell"]
                results_mapped = [[*row, ""] for row in (results_mapped or [])]

        return WebStatsTableQueryResponse(
            columns=columns,
            results=results_mapped,
            timings=response.timings,
            types=response.types,
            hogql=response.hogql,
            modifiers=self.modifiers,
            usedPreAggregatedTables=self.used_preaggregated_tables,
            **self.paginator.response_params(),
        )

    def _join_with_aggregation_value(self, breakdown_value: str, row: list):
        if self.query.breakdownBy != WebStatsBreakdown.LANGUAGE:
            return breakdown_value

        return f"{breakdown_value}-{row[3]}"  # Fourth value is the aggregation value

    def _bounce_entry_pathname_breakdown(self):
        return self._apply_path_cleaning(ast.Field(chain=["session", "$entry_pathname"]))

    def _counts_breakdown_value(self):
        config = BREAKDOWN_CONFIGS.get(self.query.breakdownBy)

        if config is None:
            raise NotImplementedError(f"Breakdown {self.query.breakdownBy} not implemented")

        return config.build_expr(self._apply_path_cleaning)


def coalesce_with_null_display(*exprs: ast.Expr) -> ast.Expr:
    return ast.Call(name="coalesce", args=[*exprs, ast.Constant(value=BREAKDOWN_NULL_DISPLAY)])
