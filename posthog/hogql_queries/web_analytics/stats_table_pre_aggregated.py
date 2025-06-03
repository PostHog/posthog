from typing import TYPE_CHECKING, Literal, cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.web_analytics.pre_aggregated.query_builder import WebAnalyticsPreAggregatedQueryBuilder
from posthog.hogql_queries.web_analytics.pre_aggregated.properties import STATS_TABLE_SUPPORTED_FILTERS
from posthog.schema import WebAnalyticsOrderByDirection, WebAnalyticsOrderByFields, WebStatsBreakdown

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner


class StatsTablePreAggregatedQueryBuilder(WebAnalyticsPreAggregatedQueryBuilder):
    SUPPORTED_BREAKDOWNS = [
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
        WebStatsBreakdown.TIMEZONE,
        WebStatsBreakdown.INITIAL_PAGE,
        WebStatsBreakdown.PAGE,
        WebStatsBreakdown.EXIT_PAGE,
    ]

    def __init__(self, runner: "WebStatsTableQueryRunner") -> None:
        super().__init__(runner=runner, supported_props_filters=STATS_TABLE_SUPPORTED_FILTERS)

    def can_use_preaggregated_tables(self) -> bool:
        if not super().can_use_preaggregated_tables():
            return False

        return self.runner.query.breakdownBy in self.SUPPORTED_BREAKDOWNS

    def get_query(self) -> ast.SelectQuery:
        if self._includes_current_day():
            return self._get_union_query()
        else:
            return self._get_daily_only_query()

    def _get_daily_only_query(self) -> ast.SelectQuery:
        """Query for date ranges that don't include current day - use daily tables only."""
        if self.runner.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE:
            return self._bounce_rate_query("web_bounces_daily")
        elif self.runner.query.breakdownBy == WebStatsBreakdown.PAGE:
            return self._path_query("web_stats_daily")
        else:
            return self._generic_breakdown_query("web_stats_daily")

    def _get_union_query(self) -> ast.SelectQuery:
        """Query that combines daily and hourly data using UNION ALL."""
        if self.runner.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE:
            return self._create_union_query("web_bounces_daily", "web_bounces_hourly", self._bounce_rate_template)
        elif self.runner.query.breakdownBy == WebStatsBreakdown.PAGE:
            return self._path_union_query()
        else:
            return self._create_union_query("web_stats_daily", "web_stats_hourly", self._generic_breakdown_template)

    def _generic_breakdown_query(self, table_name: str) -> ast.SelectQuery:
        """Generate a generic breakdown query for a single table."""
        previous_period_filter, current_period_filter = self.get_date_ranges()

        query = cast(
            ast.SelectQuery,
            parse_select(
                """
                SELECT
                    {breakdown_field} as `context.columns.breakdown_value`,
                    {visitors_tuple} AS `context.columns.visitors`,
                    {views_tuple} as `context.columns.views`
                FROM {table_name} FINAL
                GROUP BY `context.columns.breakdown_value`
                """,
                placeholders={
                    "table_name": ast.Field(chain=[table_name]),
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

        filters = self._get_filters(table_name=table_name)
        if filters:
            query.where = filters

        query.order_by = [self._get_order_by()]
        return query

    def _generic_breakdown_template(self) -> ast.SelectQuery:
        """Template for generic breakdown queries - to be used in UNION."""
        previous_period_filter, current_period_filter = self.get_date_ranges_for_union()

        return cast(
            ast.SelectQuery,
            parse_select(
                """
                SELECT
                    {breakdown_field} as `context.columns.breakdown_value`,
                    {visitors_tuple} AS `context.columns.visitors`,
                    {views_tuple} as `context.columns.views`
                FROM {table_name} FINAL
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

    def _bounce_rate_query(self, table_name: str) -> ast.SelectQuery:
        """Generate a bounce rate query for a single table."""
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
                FROM {table_name} FINAL
                GROUP BY `context.columns.breakdown_value`
                """,
                placeholders={
                    "table_name": ast.Field(chain=[table_name]),
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

        filters = self._get_filters(table_name=table_name)
        if filters:
            query.where = filters

        query.order_by = [self._get_order_by()]
        return query

    def _bounce_rate_template(self) -> ast.SelectQuery:
        """Template for bounce rate queries - to be used in UNION."""
        previous_period_filter, current_period_filter = self.get_date_ranges_for_union()

        return cast(
            ast.SelectQuery,
            parse_select(
                """
                SELECT
                    {breakdown_value} as `context.columns.breakdown_value`,
                    {visitors_tuple} AS `context.columns.visitors`,
                    {views_tuple} as `context.columns.views`,
                    {bounce_rate_tuple} as `context.columns.bounce_rate`
                FROM {table_name} FINAL
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

    def _create_union_query(self, daily_table: str, hourly_table: str, query_template_func) -> ast.SelectQuery:
        """Create a UNION ALL query from daily and hourly tables using the provided template."""
        # Create daily part - exclude current day
        daily_query = query_template_func()
        daily_query.select_from = ast.JoinExpr(table=ast.Field(chain=[daily_table]))
        daily_period_filter = self._get_daily_period_filter(daily_table, exclude_current_day=True)
        daily_query.where = self._get_filters(daily_table, daily_period_filter)

        # Create hourly part - only current day
        hourly_query = query_template_func()
        hourly_query.select_from = ast.JoinExpr(table=ast.Field(chain=[hourly_table]))
        hourly_period_filter = self._get_hourly_period_filter(hourly_table, current_day_only=True)
        hourly_query.where = self._get_filters(hourly_table, hourly_period_filter)

        # Create UNION ALL and wrap in final aggregation
        union_query = ast.SelectUnionQuery(select_queries=[daily_query, hourly_query])

        # Determine which aggregation template to use based on query type
        if self.runner.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE:
            agg_template = """
                SELECT
                    `context.columns.breakdown_value`,
                    tuple(
                        sumMerge(tupleElement(`context.columns.visitors`, 1)),
                        sumMerge(tupleElement(`context.columns.visitors`, 2))
                    ) AS `context.columns.visitors`,
                    tuple(
                        sumMerge(tupleElement(`context.columns.views`, 1)),
                        sumMerge(tupleElement(`context.columns.views`, 2))
                    ) AS `context.columns.views`,
                    tuple(
                        if(sumMerge(tupleElement(`context.columns.visitors`, 1)) > 0,
                           sumMerge(tupleElement(`context.columns.bounce_rate`, 1) * tupleElement(`context.columns.visitors`, 1)) / sumMerge(tupleElement(`context.columns.visitors`, 1)),
                           0),
                        if(sumMerge(tupleElement(`context.columns.visitors`, 2)) > 0,
                           sumMerge(tupleElement(`context.columns.bounce_rate`, 2) * tupleElement(`context.columns.visitors`, 2)) / sumMerge(tupleElement(`context.columns.visitors`, 2)),
                           0)
                    ) AS `context.columns.bounce_rate`
                FROM ({union_subquery})
                GROUP BY `context.columns.breakdown_value`
                """
        else:
            agg_template = """
                SELECT
                    `context.columns.breakdown_value`,
                    tuple(
                        sumMerge(tupleElement(`context.columns.visitors`, 1)),
                        sumMerge(tupleElement(`context.columns.visitors`, 2))
                    ) AS `context.columns.visitors`,
                    tuple(
                        sumMerge(tupleElement(`context.columns.views`, 1)),
                        sumMerge(tupleElement(`context.columns.views`, 2))
                    ) AS `context.columns.views`
                FROM ({union_subquery})
                GROUP BY `context.columns.breakdown_value`
                """

        final_query = cast(
            ast.SelectQuery,
            parse_select(
                agg_template,
                placeholders={
                    "union_subquery": union_query,
                },
            ),
        )

        final_query.order_by = [self._get_order_by()]
        return final_query

    def _path_query(self, table_name: str) -> ast.SelectQuery:
        """Generate a path query for a single table."""
        previous_period_filter, current_period_filter = self.get_date_ranges(table_name=table_name)

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
                    {table_name} FINAL
                LEFT JOIN ({bounce_subquery}) bounces
                    ON {join_condition}
                GROUP BY `context.columns.breakdown_value`
                """,
                placeholders={
                    "table_name": ast.Field(chain=[table_name]),
                    "breakdown_value": self._apply_path_cleaning(ast.Field(chain=["pathname"])),
                    "visitors_tuple": self._period_comparison_tuple(
                        "persons_uniq_state",
                        "uniqMergeIf",
                        current_period_filter,
                        previous_period_filter,
                        table_prefix=table_name,
                    ),
                    "views_tuple": self._period_comparison_tuple(
                        "pageviews_count_state",
                        "sumMergeIf",
                        current_period_filter,
                        previous_period_filter,
                        table_prefix=table_name,
                    ),
                    "bounce_subquery": self._bounce_rate_query("web_bounces_daily"),
                    "join_condition": ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=self._apply_path_cleaning(ast.Field(chain=[table_name, "pathname"])),
                        right=ast.Field(chain=["bounces", "context.columns.breakdown_value"]),
                    ),
                },
            ),
        )

        filters = self._get_filters(table_name=table_name)
        if filters:
            query.where = filters

        query.order_by = [self._get_order_by()]
        return query

    def _path_union_query(self) -> ast.SelectQuery:
        """UNION ALL version of path query combining daily and hourly data."""
        # Create separate UNION queries for stats and bounces, then join them
        stats_union = self._create_union_query("web_stats_daily", "web_stats_hourly", self._path_stats_template)
        bounces_union = self._create_union_query("web_bounces_daily", "web_bounces_hourly", self._bounce_rate_template)

        # Final query joining the two unions
        final_query = cast(
            ast.SelectQuery,
            parse_select(
                """
                SELECT
                    stats.`context.columns.breakdown_value`,
                    stats.`context.columns.visitors`,
                    stats.`context.columns.views`,
                    bounces.`context.columns.bounce_rate`
                FROM ({stats_subquery}) stats
                LEFT JOIN ({bounces_subquery}) bounces
                    ON stats.`context.columns.breakdown_value` = bounces.`context.columns.breakdown_value`
                """,
                placeholders={
                    "stats_subquery": stats_union,
                    "bounces_subquery": bounces_union,
                },
            ),
        )

        final_query.order_by = [self._get_order_by()]
        return final_query

    def _path_stats_template(self) -> ast.SelectQuery:
        """Template for path stats queries - to be used in UNION."""
        previous_period_filter, current_period_filter = self.get_date_ranges_for_union()

        return cast(
            ast.SelectQuery,
            parse_select(
                """
                SELECT
                    {breakdown_value} as `context.columns.breakdown_value`,
                    {visitors_tuple} AS `context.columns.visitors`,
                    {views_tuple} as `context.columns.views`
                FROM {table_name} FINAL
                GROUP BY `context.columns.breakdown_value`
                """,
                placeholders={
                    "breakdown_value": self._apply_path_cleaning(ast.Field(chain=["pathname"])),
                    "visitors_tuple": self._period_comparison_tuple(
                        "persons_uniq_state", "uniqMergeIf", current_period_filter, previous_period_filter
                    ),
                    "views_tuple": self._period_comparison_tuple(
                        "pageviews_count_state", "sumMergeIf", current_period_filter, previous_period_filter
                    ),
                },
            ),
        )

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
                return ast.Field(chain=["country_name"])
            case WebStatsBreakdown.REGION:
                return ast.Field(chain=["region_code"])
            case WebStatsBreakdown.CITY:
                return ast.Field(chain=["city_name"])
            case WebStatsBreakdown.TIMEZONE:
                return ast.Field(chain=["time_zone"])
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
