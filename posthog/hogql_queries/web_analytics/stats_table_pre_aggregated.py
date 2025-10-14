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
        Query that follows the standard pattern from stats_table.py to_main_query().
        Uses inner query grouped by session+breakdown, then aggregates with period comparison tuples.
        """
        # Build the inner query following _main_inner_query pattern
        inner_query = self._conversion_inner_query()

        # Build outer query with period comparison tuples like to_main_query
        selects = [
            ast.Alias(alias="context.columns.breakdown_value", expr=ast.Field(chain=["breakdown_value"])),
            self._conversion_period_tuple("filtered_person_id", "context.columns.visitors", "uniq"),
            self._conversion_period_tuple("conversion_count", "context.columns.total_conversions", "sum"),
            self._conversion_period_tuple("conversion_person_id", "context.columns.unique_conversions", "uniq"),
            ast.Alias(
                alias="context.columns.conversion_rate",
                expr=ast.Tuple(
                    exprs=[
                        parse_expr(
                            "if(`context.columns.visitors`.1 = 0, NULL, `context.columns.unique_conversions`.1 / `context.columns.visitors`.1)"
                        ),
                        parse_expr(
                            "if(`context.columns.visitors`.2 = 0, NULL, `context.columns.unique_conversions`.2 / `context.columns.visitors`.2)"
                        ),
                    ]
                ),
            ),
        ]

        query = ast.SelectQuery(
            select=selects,
            select_from=ast.JoinExpr(table=inner_query),
            group_by=[ast.Field(chain=["context.columns.breakdown_value"])],
        )

        return query

    def _conversion_inner_query(self) -> ast.SelectQuery:
        """Build inner query that mirrors _main_inner_query from stats_table.py"""
        # Get breakdown value using the runner's existing method
        breakdown = self.runner._counts_breakdown_value()

        query = parse_select(
            """
            SELECT
                any(person_id) AS filtered_person_id,
                {breakdown_value} AS breakdown_value,
                session.session_id AS session_id,
                min(session.$start_timestamp) as start_timestamp
            FROM events
            WHERE and({inside_periods}, {event_where}, {all_properties}, {where_breakdown})
            GROUP BY session_id, breakdown_value
            """,
            placeholders={
                "breakdown_value": breakdown,
                "event_where": self.runner.event_type_expr,
                "all_properties": property_to_expr(
                    self.runner.query.properties + self.runner._test_account_filters, team=self.runner.team
                ),
                "where_breakdown": self.runner.where_breakdown(),
                "inside_periods": self.runner._periods_expression("timestamp"),
            },
        )

        assert isinstance(query, ast.SelectQuery)

        # Add conversion fields just like _main_inner_query does
        if self.runner.conversion_count_expr and self.runner.conversion_person_id_expr:
            query.select.append(ast.Alias(alias="conversion_count", expr=self.runner.conversion_count_expr))
            query.select.append(ast.Alias(alias="conversion_person_id", expr=self.runner.conversion_person_id_expr))

        return query

    def _conversion_period_tuple(self, column: str, alias: str, function_name: str) -> ast.Alias:
        """Create period comparison tuple for conversion queries"""
        return ast.Alias(
            alias=alias,
            expr=ast.Tuple(
                exprs=[
                    self._conversion_current_period_agg(function_name, column),
                    self._conversion_previous_period_agg(function_name, column),
                ]
            ),
        )

    def _conversion_current_period_agg(self, function_name: str, column_name: str) -> ast.Call:
        if not self.runner.query_compare_to_date_range:
            return ast.Call(name=function_name, args=[ast.Field(chain=[column_name])])

        return ast.Call(
            name=f"{function_name}If",
            args=[
                ast.Field(chain=[column_name]),
                self.runner._current_period_expression("start_timestamp"),
            ],
        )

    def _conversion_previous_period_agg(self, function_name: str, column_name: str) -> ast.Expr:
        if not self.runner.query_compare_to_date_range:
            return ast.Constant(value=None)

        return ast.Call(
            name=f"{function_name}If",
            args=[
                ast.Field(chain=[column_name]),
                self.runner._previous_period_expression("start_timestamp"),
            ],
        )

    def get_query(self) -> ast.SelectQuery:
        # For conversion goals, use the default breakdown query which supports conversions
        if self.runner.query.conversionGoal:
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
