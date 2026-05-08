from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Optional, Union, cast

from posthog.schema import (
    CachedWebStatsTableQueryResponse,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PersonPropertyFilter,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
    WebStatsBreakdown,
    WebStatsTableQuery,
    WebStatsTableQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import (
    get_property_key,
    get_property_operator,
    get_property_type,
    get_property_value,
    property_to_expr,
)

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.web_analytics.events_prefilter import PrefilterHogQLHasMorePaginator
from posthog.hogql_queries.web_analytics.stats_table_pre_aggregated import StatsTablePreAggregatedQueryBuilder
from posthog.hogql_queries.web_analytics.stats_table_strategies import (
    FrustrationMetricsStrategy,
    MainQueryStrategy,
    PathBounceAvgTimeStrategy,
    PathBounceStrategy,
    StatsTableQueryStrategy,
)
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner, map_columns
from posthog.settings.data_stores import is_web_analytics_events_prefilter_team

BREAKDOWN_NULL_DISPLAY = "(none)"
BREAKDOWN_REFERRER_PREFIX = "referrer:"


@dataclass(frozen=True)
class StatsTableQueryPlan:
    strategy: str
    build_query: Callable[[], ast.SelectQuery]
    uses_preaggregated_tables: bool = False


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

        limit = self.query.limit if self.query.limit else None
        offset = self.query.offset if self.query.offset else None
        if is_web_analytics_events_prefilter_team(self.team.pk):
            date_from, date_to = self._events_prefilter_date_bounds()
            self.paginator = PrefilterHogQLHasMorePaginator.create(
                limit_context=LimitContext.QUERY,
                team_id=self.team.pk,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                offset=offset,
            )
        else:
            self.paginator = HogQLHasMorePaginator.from_limit_context(
                limit_context=LimitContext.QUERY,
                limit=limit,
                offset=offset,
            )

        self.preaggregated_query_builder = StatsTablePreAggregatedQueryBuilder(self)

    def _resolve_query_plan(self) -> StatsTableQueryPlan:
        if (
            self.modifiers
            and self.modifiers.useWebAnalyticsPreAggregatedTables
            and self.preaggregated_query_builder.can_use_preaggregated_tables()
            and not self.query.includeAvgTimeOnPage
            and not self.query.conversionGoal
        ):
            if self.query.breakdownBy == WebStatsBreakdown.PAGE:
                return StatsTableQueryPlan(
                    strategy="stats_table_preaggregated_path_bounce",
                    build_query=self.preaggregated_query_builder.get_query,
                    uses_preaggregated_tables=True,
                )
            if self.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE and self.query.includeBounceRate:
                return StatsTableQueryPlan(
                    strategy="stats_table_preaggregated_entry_bounce",
                    build_query=self.preaggregated_query_builder.get_query,
                    uses_preaggregated_tables=True,
                )
            return StatsTableQueryPlan(
                strategy="stats_table_preaggregated",
                build_query=self.preaggregated_query_builder.get_query,
                uses_preaggregated_tables=True,
            )

        strategy = self._get_strategy()
        return StatsTableQueryPlan(
            strategy=self._strategy_name(strategy),
            build_query=strategy.build_query,
        )

    def query_strategy(self) -> str:
        return self._resolve_query_plan().strategy

    def clickhouse_query_type(self) -> str:
        return f"{self.query_strategy()}_query"

    def to_query(self) -> ast.SelectQuery:
        query_plan = self._resolve_query_plan()
        self.used_preaggregated_tables = query_plan.uses_preaggregated_tables
        return query_plan.build_query()

    def _strategy_name(self, strategy: StatsTableQueryStrategy) -> str:
        if isinstance(strategy, FrustrationMetricsStrategy):
            return "stats_table_frustration_metrics"
        if isinstance(strategy, PathBounceAvgTimeStrategy):
            return "stats_table_path_bounce_and_avg_time"
        if isinstance(strategy, PathBounceStrategy):
            return "stats_table_path_bounce"

        if (
            isinstance(strategy, MainQueryStrategy)
            and self.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE
            and self.query.includeBounceRate
        ):
            return "stats_table_entry_bounce"

        return "stats_table_main"

    def _get_strategy(self) -> StatsTableQueryStrategy:
        if self.query.breakdownBy == WebStatsBreakdown.FRUSTRATION_METRICS:
            return FrustrationMetricsStrategy(self)

        if self.query.breakdownBy == WebStatsBreakdown.PAGE:
            if self.query.conversionGoal:
                return MainQueryStrategy(self)
            if self.query.includeAvgTimeOnPage:
                return PathBounceAvgTimeStrategy(self)
            if self.query.includeBounceRate:
                return PathBounceStrategy(self)

        if self.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE and self.query.includeBounceRate:
            return MainQueryStrategy(self, breakdown_override=self._bounce_entry_pathname_breakdown())

        return MainQueryStrategy(self)

    def _order_by(self, columns: list[str]) -> list[ast.OrderExpr] | None:
        column = None
        direction: Literal["ASC", "DESC"] = "DESC"
        if self.query.orderBy:
            field = cast(WebAnalyticsOrderByFields, self.query.orderBy[0])
            direction = cast(WebAnalyticsOrderByDirection, self.query.orderBy[1]).value

            if field == WebAnalyticsOrderByFields.VISITORS:
                column = "context.columns.visitors"
            elif field == WebAnalyticsOrderByFields.VIEWS:
                column = "context.columns.views"
            elif field == WebAnalyticsOrderByFields.CLICKS:
                column = "context.columns.clicks"
            elif field == WebAnalyticsOrderByFields.BOUNCE_RATE:
                column = "context.columns.bounce_rate"
            elif field == WebAnalyticsOrderByFields.AVERAGE_SCROLL_PERCENTAGE:
                column = "context.columns.average_scroll_percentage"
            elif field == WebAnalyticsOrderByFields.SCROLL_GT80_PERCENTAGE:
                column = "context.columns.scroll_gt80_percentage"
            elif field == WebAnalyticsOrderByFields.TOTAL_CONVERSIONS:
                column = "context.columns.total_conversions"
            elif field == WebAnalyticsOrderByFields.UNIQUE_CONVERSIONS:
                column = "context.columns.unique_conversions"
            elif field == WebAnalyticsOrderByFields.CONVERSION_RATE:
                column = "context.columns.conversion_rate"
            elif field == WebAnalyticsOrderByFields.RAGE_CLICKS:
                column = "context.columns.rage_clicks"
            elif field == WebAnalyticsOrderByFields.DEAD_CLICKS:
                column = "context.columns.dead_clicks"
            elif field == WebAnalyticsOrderByFields.ERRORS:
                column = "context.columns.errors"

        def f(c: str) -> Optional[ast.OrderExpr]:
            return ast.OrderExpr(expr=ast.Field(chain=[c]), order=direction) if column != c and c in columns else None

        return [
            expr
            for expr in [
                # use order from query
                (
                    ast.OrderExpr(expr=ast.Field(chain=[column]), order=direction)
                    if column is not None and column in columns
                    else None
                ),
                f("context.columns.unique_conversions"),
                f("context.columns.total_conversions"),
                f("context.columns.visitors"),
                f("context.columns.views"),
                ast.OrderExpr(expr=ast.Field(chain=["context.columns.breakdown_value"]), order="ASC"),
            ]
            if expr is not None
        ]

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

    def _period_comparison_tuple(self, column, alias, function_name):
        return ast.Alias(
            alias=alias,
            expr=ast.Tuple(
                exprs=[
                    self._current_period_aggregate(function_name, column),
                    self._previous_period_aggregate(function_name, column),
                ]
            ),
        )

    def _current_period_aggregate(self, function_name, column_name):
        if not self.query_compare_to_date_range:
            return ast.Call(name=function_name, args=[ast.Field(chain=[column_name])])

        return self.period_aggregate(
            function_name,
            column_name,
            self.query_date_range.date_from_as_hogql(),
            self.query_date_range.date_to_as_hogql(),
        )

    def _previous_period_aggregate(self, function_name, column_name):
        if not self.query_compare_to_date_range:
            return ast.Constant(value=None)

        return self.period_aggregate(
            function_name,
            column_name,
            self.query_compare_to_date_range.date_from_as_hogql(),
            self.query_compare_to_date_range.date_to_as_hogql(),
        )

    def _event_properties(self) -> ast.Expr:
        properties = [
            p
            for p in self.query.properties + self._test_account_filters
            if get_property_type(p) in ["event", "person", "cohort"]
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def _event_properties_for_scroll(self) -> ast.Expr:
        def map_scroll_property(property: Union[EventPropertyFilter, PersonPropertyFilter]):
            if get_property_type(property) == "event" and get_property_key(property) == "$pathname":
                return EventPropertyFilter(
                    key="$prev_pageview_pathname",
                    operator=get_property_operator(property),
                    value=get_property_value(property),
                )
            return property

        properties = [
            map_scroll_property(p)
            for p in self.query.properties + self._test_account_filters
            if get_property_type(p) in ["event", "person", "cohort"]
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def _event_properties_for_bounce_rate(self) -> ast.Expr:
        # Exclude pathname filters for bounce rate calculation
        #
        # This provides consistent bounce rates when filtering by multiple pathnames.
        # Without this, pathname filters would affect which sessions are considered for the
        # bounce rates calculations but since we group them by entry_pathname, the results could be misleading
        # as the events would be filtered by a IN(pathname) and the bounce shown would be for the first pathname
        # which users are not necessarily expecting to see.
        properties = [
            p
            for p in self.query.properties + self._test_account_filters
            if not (get_property_type(p) == "event" and get_property_key(p) == "$pathname")
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def _session_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) == "session"
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def _all_properties(self) -> ast.Expr:
        properties = self.query.properties + self._test_account_filters
        return property_to_expr(properties, team=self.team)

    def _calculate(self):
        query = self.to_query()

        # Pre-aggregated tables store data in UTC **buckets**, so we need to disable timezone conversion
        # to prevent HogQL from automatically converting DateTime fields to team timezone
        modifiers = self.modifiers
        if self.used_preaggregated_tables:
            modifiers = self.modifiers.model_copy() if self.modifiers else HogQLQueryModifiers()
            modifiers.convertToProjectTimezone = False

        response = self.paginator.execute_hogql_query(
            query_type=self.clickhouse_query_type(),
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

    def _prepend_host(self, host_expr: ast.Expr, path_expr: ast.Expr) -> ast.Expr:
        return ast.Call(
            name="nullIf",
            args=[
                ast.Call(
                    name="concat",
                    args=[host_expr, path_expr],
                ),
                ast.Constant(value=""),
            ],
        )

    def _counts_breakdown_value(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.PAGE:
                path = self._apply_path_cleaning(ast.Field(chain=["events", "properties", "$pathname"]))
                if self.query.includeHost:
                    return self._prepend_host(ast.Field(chain=["events", "properties", "$host"]), path)
                return path
            case WebStatsBreakdown.INITIAL_PAGE:
                path = self._apply_path_cleaning(ast.Field(chain=["session", "$entry_pathname"]))
                if self.query.includeHost:
                    return self._prepend_host(ast.Field(chain=["session", "$entry_hostname"]), path)
                return path
            case WebStatsBreakdown.EXIT_PAGE:
                path = self._apply_path_cleaning(ast.Field(chain=["session", "$end_pathname"]))
                if self.query.includeHost:
                    return self._prepend_host(ast.Field(chain=["session", "$end_hostname"]), path)
                return path
            case WebStatsBreakdown.EXIT_CLICK:
                return ast.Field(chain=["session", "$last_external_click_url"])
            case WebStatsBreakdown.PREVIOUS_PAGE:
                return ast.Call(
                    name="multiIf",
                    args=[
                        # if it's internal navigation within a SPA, use the previous pageview's pathname
                        ast.Call(
                            name="isNotNull",
                            args=[ast.Field(chain=["events", "properties", "$prev_pageview_pathname"])],
                        ),
                        self._apply_path_cleaning(ast.Field(chain=["events", "properties", "$prev_pageview_pathname"])),
                        # if it's internal navigation but not within a SPA, the referrer will be on the same domain, and path cleaning should still be applied
                        ast.Call(
                            name="equals",
                            args=[
                                ast.Call(
                                    name="domain", args=[ast.Field(chain=["events", "properties", "$current_url"])]
                                ),
                                ast.Call(name="domain", args=[ast.Field(chain=["events", "properties", "$referrer"])]),
                            ],
                        ),
                        self._apply_path_cleaning(
                            ast.Call(name="path", args=[ast.Field(chain=["events", "properties", "$referrer"])])
                        ),
                        # a visit from an external domain
                        ast.Field(chain=["events", "properties", "$referrer"]),
                    ],
                )
            case WebStatsBreakdown.SCREEN_NAME:
                return ast.Field(chain=["events", "properties", "$screen_name"])
            case WebStatsBreakdown.INITIAL_REFERRING_DOMAIN:
                return ast.Field(chain=["session", "$entry_referring_domain"])
            case WebStatsBreakdown.INITIAL_REFERRING_URL:
                return ast.Call(
                    name="cutQueryStringAndFragment",
                    args=[ast.Field(chain=["events", "properties", "$session_entry_referrer"])],
                )
            case WebStatsBreakdown.INITIAL_UTM_SOURCE:
                return ast.Field(chain=["session", "$entry_utm_source"])
            case WebStatsBreakdown.INITIAL_UTM_CAMPAIGN:
                return ast.Field(chain=["session", "$entry_utm_campaign"])
            case WebStatsBreakdown.INITIAL_UTM_MEDIUM:
                return ast.Field(chain=["session", "$entry_utm_medium"])
            case WebStatsBreakdown.INITIAL_UTM_TERM:
                return ast.Field(chain=["session", "$entry_utm_term"])
            case WebStatsBreakdown.INITIAL_UTM_CONTENT:
                return ast.Field(chain=["session", "$entry_utm_content"])
            case WebStatsBreakdown.INITIAL_CHANNEL_TYPE:
                return ast.Field(chain=["session", "$channel_type"])
            case WebStatsBreakdown.INITIAL_UTM_SOURCE_MEDIUM_CAMPAIGN:
                # The source part uses a prefix so the frontend can distinguish
                # whether the value came from $entry_utm_source or $entry_referring_domain
                source_expr = ast.Call(
                    name="if",
                    args=[
                        ast.Call(
                            name="isNotNull",
                            args=[ast.Field(chain=["session", "$entry_utm_source"])],
                        ),
                        ast.Field(chain=["session", "$entry_utm_source"]),
                        ast.Call(
                            name="if",
                            args=[
                                ast.Call(
                                    name="isNotNull",
                                    args=[ast.Field(chain=["session", "$entry_referring_domain"])],
                                ),
                                ast.Call(
                                    name="concat",
                                    args=[
                                        ast.Constant(value=BREAKDOWN_REFERRER_PREFIX),
                                        ast.Field(chain=["session", "$entry_referring_domain"]),
                                    ],
                                ),
                                ast.Constant(value=BREAKDOWN_NULL_DISPLAY),
                            ],
                        ),
                    ],
                )
                return ast.Call(
                    name="concatWithSeparator",
                    args=[
                        ast.Constant(value=" / "),
                        source_expr,
                        coalesce_with_null_display(ast.Field(chain=["session", "$entry_utm_medium"])),
                        coalesce_with_null_display(ast.Field(chain=["session", "$entry_utm_campaign"])),
                    ],
                )
            case WebStatsBreakdown.BROWSER:
                return ast.Field(chain=["properties", "$browser"])
            case WebStatsBreakdown.OS:
                return ast.Field(chain=["properties", "$os"])
            case WebStatsBreakdown.VIEWPORT:
                return ast.Tuple(
                    exprs=[
                        ast.Field(chain=["properties", "$viewport_width"]),
                        ast.Field(chain=["properties", "$viewport_height"]),
                    ]
                )
            case WebStatsBreakdown.DEVICE_TYPE:
                return ast.Field(chain=["properties", "$device_type"])
            case WebStatsBreakdown.COUNTRY:
                return ast.Field(chain=["properties", "$geoip_country_code"])
            case WebStatsBreakdown.REGION:
                return parse_expr(
                    "tuple(properties.$geoip_country_code, properties.$geoip_subdivision_1_code, properties.$geoip_subdivision_1_name)"
                )
            case WebStatsBreakdown.CITY:
                return parse_expr("tuple(properties.$geoip_country_code, properties.$geoip_city_name)")
            case WebStatsBreakdown.LANGUAGE:
                return ast.Field(chain=["properties", "$browser_language"])
            case WebStatsBreakdown.TIMEZONE:
                # Value is in minutes, turn it to hours, works even for fractional timezone offsets (I'm looking at you, Australia)
                # see the docs here for why this the negative is necessary
                # https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Date/getTimezoneOffset#negative_values_and_positive_values
                # the example given is that for UTC+10, -600 will be returned.
                return parse_expr("-toFloat(properties.$timezone_offset) / 60")
            case WebStatsBreakdown.FRUSTRATION_METRICS:
                return self._apply_path_cleaning(ast.Field(chain=["events", "properties", "$pathname"]))
            case _:
                raise NotImplementedError("Breakdown not implemented")

    def _processed_breakdown_value(self):
        if self.query.breakdownBy == WebStatsBreakdown.LANGUAGE:
            return parse_expr("arrayElement(splitByChar('-', assumeNotNull(breakdown_value), 2), 1)")

        return ast.Field(chain=["breakdown_value"])

    def _include_extra_aggregation_value(self):
        return self.query.breakdownBy == WebStatsBreakdown.LANGUAGE

    def _extra_aggregation_value(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.LANGUAGE:
                return parse_expr(
                    "arrayElement(topK(1)(arrayElement(splitByChar('-', assumeNotNull(breakdown_value), 2), 2)), 1) AS `context.columns.aggregation_value`"
                )
            case _:
                raise NotImplementedError("Aggregation value not exists")

    def outer_where_breakdown(self) -> ast.Expr | None:
        match self.query.breakdownBy:
            case WebStatsBreakdown.REGION | WebStatsBreakdown.CITY:
                return parse_expr("tupleElement(`context.columns.breakdown_value`, 2) IS NOT NULL")
            case WebStatsBreakdown.VIEWPORT:
                return parse_expr(
                    "tupleElement(`context.columns.breakdown_value`, 1) IS NOT NULL AND tupleElement(`context.columns.breakdown_value`, 2) IS NOT NULL AND "
                    "tupleElement(`context.columns.breakdown_value`, 1) != 0 AND tupleElement(`context.columns.breakdown_value`, 2) != 0"
                )
            case (
                WebStatsBreakdown.INITIAL_UTM_SOURCE
                | WebStatsBreakdown.INITIAL_UTM_CAMPAIGN
                | WebStatsBreakdown.INITIAL_UTM_MEDIUM
                | WebStatsBreakdown.INITIAL_UTM_TERM
                | WebStatsBreakdown.INITIAL_UTM_CONTENT
            ):
                return None  # actually show null values
            case WebStatsBreakdown.INITIAL_CHANNEL_TYPE:
                return parse_expr(
                    "`context.columns.breakdown_value` IS NOT NULL AND `context.columns.breakdown_value` != ''"
                )  # we need to check for empty strings as well due to how the left join works
            case _:
                return parse_expr("`context.columns.breakdown_value` IS NOT NULL")

    def _scroll_prev_pathname_breakdown(self):
        path = self._apply_path_cleaning(ast.Field(chain=["events", "properties", "$prev_pageview_pathname"]))
        if self.query.includeHost:
            return self._prepend_host(ast.Field(chain=["events", "properties", "$host"]), path)
        return path

    def _bounce_entry_pathname_breakdown(self):
        path = self._apply_path_cleaning(ast.Field(chain=["session", "$entry_pathname"]))
        if self.query.includeHost:
            return self._prepend_host(ast.Field(chain=["session", "$entry_hostname"]), path)
        return path


def coalesce_with_null_display(*exprs: ast.Expr) -> ast.Expr:
    return ast.Call(name="coalesce", args=[*exprs, ast.Constant(value=BREAKDOWN_NULL_DISPLAY)])
