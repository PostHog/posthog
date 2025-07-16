from typing import TYPE_CHECKING, Literal, cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.web_analytics.pre_aggregated.query_builder import WebAnalyticsPreAggregatedQueryBuilder
from posthog.hogql_queries.web_analytics.pre_aggregated.properties import STATS_TABLE_SUPPORTED_FILTERS
from posthog.schema import WebAnalyticsOrderByDirection, WebAnalyticsOrderByFields, WebStatsBreakdown

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner


WEB_ANALYTICS_STATS_TABLE_PRE_AGGREGATED_SUPPORTED_BREAKDOWNS = [
    WebStatsBreakdown.DEVICE_TYPE,
    WebStatsBreakdown.BROWSER,
    WebStatsBreakdown.OS,
    WebStatsBreakdown.VIEWPORT,
    WebStatsBreakdown.INITIAL_REFERRING_DOMAIN,
    WebStatsBreakdown.INITIAL_UTM_SOURCE,
    WebStatsBreakdown.INITIAL_UTM_MEDIUM,
    WebStatsBreakdown.INITIAL_UTM_CAMPAIGN,
    WebStatsBreakdown.INITIAL_UTM_TERM,
    WebStatsBreakdown.INITIAL_UTM_CONTENT,
    WebStatsBreakdown.COUNTRY,
    WebStatsBreakdown.REGION,
    WebStatsBreakdown.CITY,
    WebStatsBreakdown.INITIAL_PAGE,
    WebStatsBreakdown.PAGE,
    WebStatsBreakdown.EXIT_PAGE,
]


class StatsTablePreAggregatedQueryBuilder(WebAnalyticsPreAggregatedQueryBuilder):
    def __init__(self, runner: "WebStatsTableQueryRunner") -> None:
        super().__init__(runner=runner, supported_props_filters=STATS_TABLE_SUPPORTED_FILTERS)

    def can_use_preaggregated_tables(self) -> bool:
        if not super().can_use_preaggregated_tables():
            return False

        return self.runner.query.breakdownBy in WEB_ANALYTICS_STATS_TABLE_PRE_AGGREGATED_SUPPORTED_BREAKDOWNS

    def _bounce_rate_query(self) -> ast.SelectQuery:
        # Like in the original stats_table, we will need this method to build the "Paths" tile so it is a special breakdown
        previous_period_filter, current_period_filter = self.get_date_ranges()

        query = cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT
                {breakdown_value} as `context.columns.breakdown_value`,
                {visitors_tuple} AS `context.columns.visitors`,
                {views_tuple} as `context.columns.views`,
                {bounce_rate_tuple} as `context.columns.bounce_rate`
            FROM web_bounces_combined
            GROUP BY `context.columns.breakdown_value`
            """,
                placeholders={
                    "breakdown_value": self._apply_path_cleaning(ast.Field(chain=["entry_pathname"])),
                    "visitors_tuple": self._period_comparison_tuple(
                        "persons_uniq_state", "uniqMergeIf", current_period_filter, previous_period_filter
                    ),
                    "views_tuple": self._period_comparison_tuple(
                        "pageviews_count_state", "sumMergeIf", current_period_filter, previous_period_filter
                    ),
                    "bounce_rate_tuple": self._bounce_rate_calculation_tuple(
                        current_period_filter, previous_period_filter
                    ),
                },
            ),
        )

        return query

    def _path_query(self) -> ast.SelectQuery:
        previous_period_filter, current_period_filter = self.get_date_ranges(table_name="web_stats_combined")

        query = cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT
                {breakdown_value} as `context.columns.breakdown_value`,
                {visitors_tuple} AS `context.columns.visitors`,
                {views_tuple} as `context.columns.views`,
                any(bounces.`context.columns.bounce_rate`) as `context.columns.bounce_rate`
            FROM
                web_stats_combined
            LEFT JOIN ({bounce_subquery}) bounces
                ON {join_condition}
            GROUP BY `context.columns.breakdown_value`
            """,
                placeholders={
                    "breakdown_value": self._apply_path_cleaning(ast.Field(chain=["pathname"])),
                    "visitors_tuple": self._period_comparison_tuple(
                        "persons_uniq_state",
                        "uniqMergeIf",
                        current_period_filter,
                        previous_period_filter,
                        table_prefix="web_stats_combined",
                    ),
                    "views_tuple": self._period_comparison_tuple(
                        "pageviews_count_state",
                        "sumMergeIf",
                        current_period_filter,
                        previous_period_filter,
                        table_prefix="web_stats_combined",
                    ),
                    "bounce_subquery": self._bounce_rate_query(),
                    "join_condition": ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=self._apply_path_cleaning(ast.Field(chain=["web_stats_combined", "pathname"])),
                        right=ast.Field(chain=["bounces", "context.columns.breakdown_value"]),
                    ),
                },
            ),
        )

        return query

    def get_query(self) -> ast.SelectQuery:
        if self.runner.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE:
            query = self._bounce_rate_query()
            table_name = "web_bounces_combined"
        elif self.runner.query.breakdownBy == WebStatsBreakdown.PAGE:
            query = self._path_query()
            table_name = "web_stats_combined"
        else:
            previous_period_filter, current_period_filter = self.get_date_ranges()

            query = cast(
                ast.SelectQuery,
                parse_select(
                    """
                SELECT
                    {breakdown_field} as `context.columns.breakdown_value`,
                    {visitors_tuple} AS `context.columns.visitors`,
                    {views_tuple} as `context.columns.views`
                FROM web_stats_combined
                GROUP BY `context.columns.breakdown_value`
                """,
                    placeholders={
                        "breakdown_field": self._get_breakdown_field(),
                        "visitors_tuple": self._period_comparison_tuple(
                            "persons_uniq_state", "uniqMergeIf", current_period_filter, previous_period_filter
                        ),
                        "views_tuple": self._period_comparison_tuple(
                            "pageviews_count_state", "sumMergeIf", current_period_filter, previous_period_filter
                        ),
                    },
                ),
            )
            table_name = "web_stats_combined"

        filters = self._get_filters(table_name=table_name)
        if filters:
            query.where = filters

        query.order_by = [self._get_order_by()]

        return query

    def _get_order_by(self):
        if self.runner.query.orderBy:
            column = None
            direction: Literal["ASC", "DESC"] = "DESC"
            field = cast(WebAnalyticsOrderByFields, self.runner.query.orderBy[0])
            direction = cast(WebAnalyticsOrderByDirection, self.runner.query.orderBy[1]).value

            if field == WebAnalyticsOrderByFields.VISITORS:
                column = "context.columns.visitors"
            elif field == WebAnalyticsOrderByFields.VIEWS:
                column = "context.columns.views"
            elif field == WebAnalyticsOrderByFields.BOUNCE_RATE and self.runner.query.breakdownBy in [
                WebStatsBreakdown.INITIAL_PAGE,
                WebStatsBreakdown.PAGE,
            ]:
                column = "context.columns.bounce_rate"

            if column:
                return ast.OrderExpr(expr=ast.Field(chain=[column]), order=direction)

        return ast.OrderExpr(expr=ast.Field(chain=["context.columns.views"]), order="DESC")

    def _get_breakdown_field(self):
        match self.runner.query.breakdownBy:
            case WebStatsBreakdown.DEVICE_TYPE:
                return ast.Field(chain=["device_type"])
            case WebStatsBreakdown.BROWSER:
                return ast.Field(chain=["browser"])
            case WebStatsBreakdown.OS:
                return ast.Field(chain=["os"])
            case WebStatsBreakdown.VIEWPORT:
                return ast.Call(
                    name="concat",
                    args=[
                        ast.Call(
                            name="toString",
                            args=[ast.Field(chain=["viewport_width"])],
                        ),
                        ast.Constant(value="x"),
                        ast.Call(
                            name="toString",
                            args=[ast.Field(chain=["viewport_height"])],
                        ),
                    ],
                )
            case WebStatsBreakdown.INITIAL_REFERRING_DOMAIN:
                return ast.Field(chain=["referring_domain"])
            case WebStatsBreakdown.INITIAL_UTM_SOURCE:
                return ast.Field(chain=["utm_source"])
            case WebStatsBreakdown.INITIAL_UTM_MEDIUM:
                return ast.Field(chain=["utm_medium"])
            case WebStatsBreakdown.INITIAL_UTM_CAMPAIGN:
                return ast.Field(chain=["utm_campaign"])
            case WebStatsBreakdown.INITIAL_UTM_TERM:
                return ast.Field(chain=["utm_term"])
            case WebStatsBreakdown.INITIAL_UTM_CONTENT:
                return ast.Field(chain=["utm_content"])
            case WebStatsBreakdown.COUNTRY:
                return ast.Field(chain=["country_code"])
            case WebStatsBreakdown.REGION:
                return ast.Field(chain=["region_code"])
            case WebStatsBreakdown.CITY:
                return ast.Field(chain=["city_name"])
            case WebStatsBreakdown.EXIT_PAGE:
                return self._apply_path_cleaning(ast.Field(chain=["end_pathname"]))

    def _apply_path_cleaning(self, path_expr: ast.Expr) -> ast.Expr:
        """Apply path cleaning to path expressions, similar to the non-pre-aggregated version"""
        if not self.runner.query.doPathCleaning:
            return path_expr

        return self.runner._apply_path_cleaning(path_expr)

    def _period_comparison_tuple(
        self,
        state_field: str,
        function_name: str,
        current_period_filter: ast.Expr,
        previous_period_filter: ast.Expr,
        table_prefix: str | None = None,
    ) -> ast.Tuple:
        field_chain: list[str | int] = [table_prefix, state_field] if table_prefix else [state_field]

        return ast.Tuple(
            exprs=[
                ast.Call(
                    name=function_name,
                    args=[
                        ast.Field(chain=field_chain),
                        current_period_filter,
                    ],
                ),
                ast.Call(
                    name=function_name,
                    args=[
                        ast.Field(chain=field_chain),
                        previous_period_filter,
                    ],
                ),
            ]
        )

    def _bounce_rate_calculation_tuple(
        self, current_period_filter: ast.Expr, previous_period_filter: ast.Expr
    ) -> ast.Tuple:
        def safe_bounce_rate(period_filter: ast.Expr) -> ast.Call:
            return ast.Call(
                name="divide",
                args=[
                    ast.Call(
                        name="sumMergeIf",
                        args=[
                            ast.Field(chain=["bounces_count_state"]),
                            period_filter,
                        ],
                    ),
                    ast.Call(
                        name="nullif",
                        args=[
                            ast.Call(
                                name="uniqMergeIf",
                                args=[
                                    ast.Field(chain=["sessions_uniq_state"]),
                                    period_filter,
                                ],
                            ),
                            ast.Constant(value=0),
                        ],
                    ),
                ],
            )

        return ast.Tuple(
            exprs=[
                safe_bounce_rate(current_period_filter),
                safe_bounce_rate(previous_period_filter),
            ]
        )
