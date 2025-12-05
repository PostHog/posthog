from typing import TYPE_CHECKING, Literal, Optional, cast

from posthog.schema import WebAnalyticsOrderByDirection, WebAnalyticsOrderByFields, WebStatsBreakdown

from posthog.hogql import ast
from posthog.hogql.database.schema.channel_type import (
    ChannelTypeExprs,
    create_channel_type_expr,
    wrap_with_null_if_empty,
)
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.web_analytics.pre_aggregated.properties import STATS_TABLE_SUPPORTED_FILTERS
from posthog.hogql_queries.web_analytics.pre_aggregated.query_builder import WebAnalyticsPreAggregatedQueryBuilder

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
    WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
]


def _nullif_empty_decorator(func):
    def wrapper(self):
        result = func(self)
        return wrap_with_null_if_empty(result)

    return wrapper


class StatsTablePreAggregatedQueryBuilder(WebAnalyticsPreAggregatedQueryBuilder):
    # Toggle this to switch between hybrid (False) and bounce-style (True) conversion query implementations
    # We could've made this a setting, but I think this way will work, but wanted to have them both around for comparing snapshots for a bit
    USE_BOUNCE_STYLE_CONVERSION_QUERY = False

    def __init__(self, runner: "WebStatsTableQueryRunner") -> None:
        super().__init__(runner=runner, supported_props_filters=STATS_TABLE_SUPPORTED_FILTERS)

    def can_use_preaggregated_tables(self) -> bool:
        if not super().can_use_preaggregated_tables():
            return False

        return self.runner.query.breakdownBy in WEB_ANALYTICS_STATS_TABLE_PRE_AGGREGATED_SUPPORTED_BREAKDOWNS

    def _get_channel_type_expr(self) -> ast.Expr:
        """Create a channel type expression using the available fields in pre-aggregated tables."""

        def _wrap_with_lower(expr: ast.Expr) -> ast.Expr:
            return ast.Call(name="lower", args=[expr])

        channel_type_exprs = ChannelTypeExprs(
            campaign=_wrap_with_lower(wrap_with_null_if_empty(ast.Field(chain=["utm_campaign"]))),
            medium=_wrap_with_lower(wrap_with_null_if_empty(ast.Field(chain=["utm_medium"]))),
            source=_wrap_with_lower(wrap_with_null_if_empty(ast.Field(chain=["utm_source"]))),
            referring_domain=wrap_with_null_if_empty(ast.Field(chain=["referring_domain"])),
            url=ast.Constant(value=None),  # URL not available in pre-aggregated tables
            hostname=ast.Field(chain=["host"]),
            pathname=ast.Field(chain=["entry_pathname"]),
            has_gclid=ast.Field(chain=["has_gclid"]),
            has_fbclid=ast.Field(chain=["has_fbclid"]),
            # To keep this compatible with the non-pre-aggregated version, we need to return '1' when the boolean is true, null otherwise
            gad_source=ast.Call(
                name="if",
                args=[
                    ast.Field(chain=["has_gad_source_paid_search"]),
                    ast.Constant(value="1"),
                    ast.Constant(value=None),
                ],
            ),
        )

        return create_channel_type_expr(
            custom_rules=None,  # Custom rules not supported for pre-aggregated tables yet
            source_exprs=channel_type_exprs,
            timings=self.runner.timings,
        )

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
            FROM {bounce_table}
            WHERE and({filters}, {breakdown_value} IS NOT NULL)
            GROUP BY `context.columns.breakdown_value`
            """,
                placeholders={
                    "bounce_table": ast.Field(chain=[self.bounces_table]),
                    "breakdown_value": ast.Call(
                        name="nullIf",
                        args=[self._apply_path_cleaning(ast.Field(chain=["entry_pathname"])), ast.Constant(value="")],
                    ),
                    "visitors_tuple": self._period_comparison_tuple(
                        "persons_uniq_state", "uniqMergeIf", current_period_filter, previous_period_filter
                    ),
                    "views_tuple": self._period_comparison_tuple(
                        "pageviews_count_state", "sumMergeIf", current_period_filter, previous_period_filter
                    ),
                    "bounce_rate_tuple": self._bounce_rate_calculation_tuple(
                        current_period_filter, previous_period_filter
                    ),
                    "filters": self._get_bounce_rate_filters(),
                },
            ),
        )

        return query

    def _get_bounce_rate_filters(self) -> ast.Expr:
        return self._get_filters(
            table_name=self.bounces_table,
            exclude_pathname=True,
        )

    def _path_query(self) -> ast.SelectQuery:
        previous_period_filter, current_period_filter = self.get_date_ranges(table_name=self.stats_table)

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
                {stats_table}
            LEFT JOIN ({bounce_subquery}) bounces
                ON {join_condition}
            WHERE and({filters}, {breakdown_value} IS NOT NULL)
            GROUP BY `context.columns.breakdown_value`
            """,
                placeholders={
                    "stats_table": ast.Field(chain=[self.stats_table]),
                    "breakdown_value": ast.Call(
                        name="nullIf",
                        args=[self._apply_path_cleaning(ast.Field(chain=["pathname"])), ast.Constant(value="")],
                    ),
                    "visitors_tuple": self._period_comparison_tuple(
                        "persons_uniq_state",
                        "uniqMergeIf",
                        current_period_filter,
                        previous_period_filter,
                        table_prefix=self.stats_table,
                    ),
                    "views_tuple": self._period_comparison_tuple(
                        "pageviews_count_state",
                        "sumMergeIf",
                        current_period_filter,
                        previous_period_filter,
                        table_prefix=self.stats_table,
                    ),
                    "bounce_subquery": self._bounce_rate_query(),
                    "join_condition": ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=self._apply_path_cleaning(
                            ast.Field(
                                chain=[
                                    self.stats_table,
                                    "pathname",
                                ]
                            )
                        ),
                        right=ast.Field(chain=["bounces", "context.columns.breakdown_value"]),
                    ),
                    "filters": self._get_filters(table_name=self.stats_table),
                },
            ),
        )

        return query

    def _default_breakdown_query(self) -> ast.SelectQuery:
        previous_period_filter, current_period_filter = self.get_date_ranges()

        if self.runner.query.conversionGoal:
            # For conversion goals, we need to join events table with pre-aggregated table
            return self._default_breakdown_query_with_conversions(current_period_filter, previous_period_filter)

        query = cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT
                {breakdown_field} as `context.columns.breakdown_value`,
                {visitors_tuple} AS `context.columns.visitors`,
                {views_tuple} as `context.columns.views`
            FROM {stats_table}
            WHERE {filters}
            GROUP BY `context.columns.breakdown_value`
            """,
                placeholders={
                    "stats_table": ast.Field(chain=[self.stats_table]),
                    "breakdown_field": self._get_breakdown_field(),
                    "visitors_tuple": self._period_comparison_tuple(
                        "persons_uniq_state", "uniqMergeIf", current_period_filter, previous_period_filter
                    ),
                    "views_tuple": self._period_comparison_tuple(
                        "pageviews_count_state", "sumMergeIf", current_period_filter, previous_period_filter
                    ),
                    "filters": self._get_filters(table_name=self.stats_table),
                },
            ),
        )

        return query

    def _default_breakdown_query_with_conversions(
        self, current_period_filter: ast.Expr, previous_period_filter: ast.Expr
    ) -> ast.SelectQuery:
        """
        Hybrid approach: pre-aggregated tables for visitors, raw events for conversions.
        Much simpler than querying everything from raw events.
        """
        # Build stats subquery from pre-aggregated table for visitor counts
        stats_subquery = self._build_stats_subquery(current_period_filter, previous_period_filter)

        # Build conversion subquery from raw events
        conversion_subquery = self._build_conversion_subquery()

        # Combine both queries
        query = cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT
                stats.breakdown_value as `context.columns.breakdown_value`,
                tuple(stats.visitors_current, stats.visitors_previous) AS `context.columns.visitors`,
                tuple(
                    coalesce(conversions.total_conversions_current, 0),
                    coalesce(conversions.total_conversions_previous, 0)
                ) as `context.columns.total_conversions`,
                tuple(
                    coalesce(conversions.unique_conversions_current, 0),
                    coalesce(conversions.unique_conversions_previous, 0)
                ) as `context.columns.unique_conversions`,
                tuple(
                    if(stats.visitors_current = 0, NULL, conversions.unique_conversions_current / stats.visitors_current),
                    if(stats.visitors_previous = 0, NULL, conversions.unique_conversions_previous / stats.visitors_previous)
                ) as `context.columns.conversion_rate`
            FROM {stats_subquery} as stats
            LEFT JOIN {conversion_subquery} as conversions
                ON stats.breakdown_value = conversions.breakdown_value
            """,
                placeholders={
                    "stats_subquery": stats_subquery,
                    "conversion_subquery": conversion_subquery,
                },
            ),
        )

        return query

    def _build_stats_subquery(
        self, current_period_filter: ast.Expr, previous_period_filter: ast.Expr
    ) -> ast.SelectQuery:
        """
        Query pre-aggregated table for visitor counts per breakdown.
        Uses the same breakdown expression as raw events to ensure JOIN matches.
        """
        # Use runner's breakdown logic to ensure consistency with conversion subquery
        breakdown_expr = self._get_breakdown_field()

        stats_select_columns = [
            ast.Alias(alias="breakdown_value", expr=breakdown_expr),
            ast.Alias(
                alias="visitors_current",
                expr=ast.Call(
                    name="uniqMergeIf",
                    args=[ast.Field(chain=["persons_uniq_state"]), current_period_filter],
                ),
            ),
            ast.Alias(
                alias="visitors_previous",
                expr=(
                    ast.Call(
                        name="uniqMergeIf",
                        args=[ast.Field(chain=["persons_uniq_state"]), previous_period_filter],
                    )
                    if self.runner.query_compare_to_date_range
                    else ast.Constant(value=0)
                ),
            ),
        ]

        stats_query = ast.SelectQuery(
            select=cast(list[ast.Expr], stats_select_columns),
            select_from=ast.JoinExpr(table=ast.Field(chain=[self.stats_table])),
            where=self._get_filters(table_name=self.stats_table),
            group_by=[breakdown_expr],
        )

        return stats_query

    def _build_conversion_subquery(self) -> ast.SelectQuery:
        """Build subquery that gets conversion counts from raw events, grouped by breakdown"""
        # Get breakdown value using the runner's existing method
        breakdown = self.runner._counts_breakdown_value()

        # Inner query: group by session and breakdown, count conversions per session
        inner_query = parse_select(
            """
            SELECT
                {breakdown_value} AS breakdown_value,
                session.session_id AS session_id,
                min(session.$start_timestamp) as start_timestamp,
                {conversion_count} as conversion_count,
                {conversion_person_id} as conversion_person_id
            FROM events
            WHERE and(
                {events_session_id} IS NOT NULL,
                {event_type_expr},
                {inside_timestamp_period},
                {all_properties},
                {where_breakdown}
            )
            GROUP BY session_id, breakdown_value
            """,
            placeholders={
                "breakdown_value": breakdown,
                "conversion_count": self.runner.conversion_count_expr or ast.Constant(value=0),
                "conversion_person_id": self.runner.conversion_person_id_expr or ast.Constant(value=None),
                "events_session_id": self.runner.events_session_property,
                "event_type_expr": self.runner.event_type_expr,
                "inside_timestamp_period": self.runner._periods_expression("timestamp"),
                "all_properties": property_to_expr(
                    self.runner.query.properties + self.runner._test_account_filters, team=self.runner.team
                ),
                "where_breakdown": self.runner.where_breakdown(),
            },
        )

        assert isinstance(inner_query, ast.SelectQuery)

        # Outer query: aggregate conversions per breakdown with period filtering
        conversion_select_columns = [
            ast.Alias(alias="breakdown_value", expr=ast.Field(chain=["breakdown_value"])),
            ast.Alias(
                alias="total_conversions_current",
                expr=ast.Call(
                    name="sumIf",
                    args=[
                        ast.Field(chain=["conversion_count"]),
                        self.runner._current_period_expression("start_timestamp"),
                    ],
                ),
            ),
            ast.Alias(
                alias="total_conversions_previous",
                expr=(
                    ast.Call(
                        name="sumIf",
                        args=[
                            ast.Field(chain=["conversion_count"]),
                            self.runner._previous_period_expression("start_timestamp"),
                        ],
                    )
                    if self.runner.query_compare_to_date_range
                    else ast.Constant(value=0)
                ),
            ),
            ast.Alias(
                alias="unique_conversions_current",
                expr=ast.Call(
                    name="uniqIf",
                    args=[
                        ast.Field(chain=["conversion_person_id"]),
                        self.runner._current_period_expression("start_timestamp"),
                    ],
                ),
            ),
            ast.Alias(
                alias="unique_conversions_previous",
                expr=(
                    ast.Call(
                        name="uniqIf",
                        args=[
                            ast.Field(chain=["conversion_person_id"]),
                            self.runner._previous_period_expression("start_timestamp"),
                        ],
                    )
                    if self.runner.query_compare_to_date_range
                    else ast.Constant(value=0)
                ),
            ),
        ]

        outer_query = ast.SelectQuery(
            select=cast(list[ast.Expr], conversion_select_columns),
            select_from=ast.JoinExpr(table=inner_query),
            where=self.runner._periods_expression("start_timestamp"),
            group_by=[ast.Field(chain=["breakdown_value"])],
        )

        return outer_query

    def _conversion_goal_query_bounce_style(self) -> ast.SelectQuery:
        """
        Bounce-rate-style approach: Query stats table and LEFT JOIN conversion subquery.
        Similar pattern to _path_query() which joins stats with bounce rate data.
        """
        previous_period_filter, current_period_filter = self.get_date_ranges(table_name=self.stats_table)

        # Build conversion subquery from raw events (reuse existing method)
        conversion_subquery = self._build_conversion_subquery()

        query = cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT
                {breakdown_value} as `context.columns.breakdown_value`,
                {visitors_tuple} AS `context.columns.visitors`,
                tuple(
                    coalesce(any(conversions.total_conversions_current), 0),
                    coalesce(any(conversions.total_conversions_previous), 0)
                ) as `context.columns.total_conversions`,
                tuple(
                    coalesce(any(conversions.unique_conversions_current), 0),
                    coalesce(any(conversions.unique_conversions_previous), 0)
                ) as `context.columns.unique_conversions`,
                tuple(
                    if(ifNull(equals(`context.columns.visitors`.1, 0), 0), NULL, divide(coalesce(any(conversions.unique_conversions_current), 0), `context.columns.visitors`.1)),
                    if(ifNull(equals(`context.columns.visitors`.2, 0), 0), NULL, divide(coalesce(any(conversions.unique_conversions_previous), 0), `context.columns.visitors`.2))
                ) as `context.columns.conversion_rate`
            FROM {stats_table}
            LEFT JOIN ({conversion_subquery}) conversions
                ON {join_condition}
            WHERE and({filters}, {breakdown_value} IS NOT NULL)
            GROUP BY `context.columns.breakdown_value`
            """,
                placeholders={
                    "stats_table": ast.Field(chain=[self.stats_table]),
                    "breakdown_value": self._get_breakdown_field(),
                    "visitors_tuple": self._period_comparison_tuple(
                        "persons_uniq_state",
                        "uniqMergeIf",
                        current_period_filter,
                        previous_period_filter,
                        table_prefix=self.stats_table,
                    ),
                    "conversion_subquery": conversion_subquery,
                    "join_condition": ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=self._get_breakdown_field(),
                        right=ast.Field(chain=["conversions", "breakdown_value"]),
                    ),
                    "filters": self._get_filters(table_name=self.stats_table),
                },
            ),
        )

        return query

    def get_query(self) -> ast.SelectQuery:
        # For conversion goals, choose implementation based on class flag
        if self.runner.query.conversionGoal:
            if self.USE_BOUNCE_STYLE_CONVERSION_QUERY:
                query = self._conversion_goal_query_bounce_style()
            else:
                query = self._default_breakdown_query()
        elif self.runner.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE:
            query = self._bounce_rate_query()
        elif self.runner.query.breakdownBy == WebStatsBreakdown.PAGE:
            query = self._path_query()
        else:
            query = self._default_breakdown_query()

        query.order_by = [self._get_order_by()]

        fill_fraction_expr = self.runner._fill_fraction(query.order_by)
        if fill_fraction_expr:
            query.select.append(fill_fraction_expr)

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
            elif field == WebAnalyticsOrderByFields.TOTAL_CONVERSIONS and self.runner.query.conversionGoal:
                column = "context.columns.total_conversions"
            elif field == WebAnalyticsOrderByFields.UNIQUE_CONVERSIONS and self.runner.query.conversionGoal:
                column = "context.columns.unique_conversions"
            elif field == WebAnalyticsOrderByFields.CONVERSION_RATE and self.runner.query.conversionGoal:
                column = "context.columns.conversion_rate"

            if column:
                return ast.OrderExpr(expr=ast.Field(chain=[column]), order=direction)

        return ast.OrderExpr(expr=ast.Field(chain=["context.columns.visitors"]), order="DESC")

    def _fill_fraction(self, order: Optional[list[ast.OrderExpr]]):
        # use whatever column we are sorting by to also visually fill the row by some fraction
        col_name = (
            order[0].expr.chain[0]
            if order and isinstance(order[0].expr, ast.Field) and len(order[0].expr.chain) == 1
            else None
        )

        if col_name:
            # for these columns, use the fraction of the overall total belonging to this row
            if col_name in [
                "context.columns.visitors",
                "context.columns.views",
                "context.columns.clicks",
                "context.columns.total_conversions",
                "context.columns.unique_conversions",
                "context.columns.rage_clicks",
                "context.columns.dead_clicks",
                "context.columns.errors",
            ]:
                return ast.Alias(
                    alias="context.columns.ui_fill_fraction",
                    expr=parse_expr(
                        "{col}.1 / sum({col}.1) OVER ()",
                        placeholders={"col": ast.Field(chain=[col_name])},
                    ),
                )
            # these columns are fractions already, use them directly
            if col_name in [
                "context.columns.bounce_rate",
                "context.columns.average_scroll_percentage",
                "context.columns.scroll_gt80_percentage",
                "context.columns.conversion_rate",
            ]:
                return ast.Alias(
                    alias="context.columns.ui_fill_fraction",
                    expr=parse_expr(
                        "{col}.1",
                        placeholders={"col": ast.Field(chain=[col_name])},
                    ),
                )
        # use visitors as a fallback
        return ast.Alias(
            alias="context.columns.ui_fill_fraction",
            expr=parse_expr(""" "context.columns.visitors".1 / sum("context.columns.visitors".1) OVER ()"""),
        )

    @_nullif_empty_decorator
    def _get_breakdown_field(self):
        match self.runner.query.breakdownBy:
            case WebStatsBreakdown.PAGE:
                return self._apply_path_cleaning(ast.Field(chain=["pathname"]))
            case WebStatsBreakdown.INITIAL_PAGE:
                return self._apply_path_cleaning(ast.Field(chain=["entry_pathname"]))
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
            case WebStatsBreakdown.INITIAL_CHANNEL_TYPE:
                return self._get_channel_type_expr()

    def _apply_path_cleaning(self, path_expr: ast.Expr) -> ast.Expr:
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

        previous_expr = (
            ast.Constant(value=None)
            if not self.runner.query_compare_to_date_range
            else ast.Call(
                name=function_name,
                args=[
                    ast.Field(chain=field_chain),
                    previous_period_filter,
                ],
            )
        )

        return ast.Tuple(
            exprs=[
                ast.Call(
                    name=function_name,
                    args=[
                        ast.Field(chain=field_chain),
                        current_period_filter,
                    ],
                ),
                previous_expr,
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

        # When there's no comparison period, return None for previous period to match regular approach
        previous_expr = (
            ast.Constant(value=None)
            if not self.runner.query_compare_to_date_range
            else safe_bounce_rate(previous_period_filter)
        )

        return ast.Tuple(
            exprs=[
                safe_bounce_rate(current_period_filter),
                previous_expr,
            ]
        )
