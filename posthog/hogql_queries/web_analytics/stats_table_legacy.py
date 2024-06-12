from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.database.schema.channel_type import create_channel_type_expr
from posthog.hogql.parser import parse_select, parse_expr
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.web_analytics.ctes import (
    COUNTS_CTE,
    BOUNCE_RATE_CTE,
    PATHNAME_SCROLL_CTE,
)
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
    map_columns,
)
from posthog.schema import (
    CachedWebStatsTableQueryResponse,
    WebStatsTableQuery,
    WebStatsBreakdown,
    WebStatsTableQueryResponse,
)


class LegacyWebStatsTableQueryRunner(WebAnalyticsQueryRunner):
    query: WebStatsTableQuery
    response: WebStatsTableQueryResponse
    cached_response: CachedWebStatsTableQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY, limit=self.query.limit if self.query.limit else None
        )

    def _bounce_rate_subquery(self):
        with self.timings.measure("bounce_rate_query"):
            return parse_select(
                BOUNCE_RATE_CTE,
                timings=self.timings,
                placeholders={
                    "session_where": self.session_where(),
                    "session_having": self.session_having(),
                    "breakdown_by": self.bounce_breakdown(),
                    "sample_rate": self._sample_ratio,
                },
            )

    def _counts_subquery(self):
        with self.timings.measure("counts_query"):
            return parse_select(
                COUNTS_CTE,
                timings=self.timings,
                placeholders={
                    "counts_where": self.events_where(),
                    "breakdown_by": self.counts_breakdown(),
                    "sample_rate": self._sample_ratio,
                },
            )

    def _scroll_depth_subquery(self):
        with self.timings.measure("scroll_depth_query"):
            return parse_select(
                PATHNAME_SCROLL_CTE,
                timings=self.timings,
                placeholders={
                    "pathname_scroll_where": self.events_where(),
                    "breakdown_by": self.counts_breakdown(),
                    "sample_rate": self._sample_ratio,
                },
            )

    def to_query(self) -> ast.SelectQuery:
        # special case for channel, as some hogql features to use the general code are still being worked on
        if self.query.breakdownBy == WebStatsBreakdown.INITIAL_CHANNEL_TYPE:
            query = self.to_channel_query()
        elif self.query.includeScrollDepth:
            query = parse_select(
                """
SELECT
    counts.breakdown_value as "context.columns.breakdown_value",
    counts.total_pageviews as "context.columns.views",
    counts.unique_visitors as "context.columns.visitors",
    bounce_rate.bounce_rate as "context.columns.bounce_rate",
    scroll_depth.average_scroll_percentage as "context.columns.average_scroll_percentage",
    scroll_depth.scroll_gt80_percentage as "context.columns.scroll_gt80_percentage"
FROM
    {counts_query} AS counts
LEFT OUTER JOIN
    {bounce_rate_query} AS bounce_rate
ON
    counts.breakdown_value = bounce_rate.breakdown_value
LEFT OUTER JOIN
    {scroll_depth_query} AS scroll_depth
ON
    counts.breakdown_value = scroll_depth.pathname
WHERE
    {where_breakdown}
ORDER BY
    "context.columns.views" DESC,
    "context.columns.breakdown_value" ASC
                """,
                timings=self.timings,
                placeholders={
                    "counts_query": self._counts_subquery(),
                    "bounce_rate_query": self._bounce_rate_subquery(),
                    "scroll_depth_query": self._scroll_depth_subquery(),
                    "where_breakdown": self.where_breakdown(),
                    "sample_rate": self._sample_ratio,
                },
            )
        elif self.query.includeBounceRate:
            with self.timings.measure("stats_table_query"):
                query = parse_select(
                    """
    SELECT
        counts.breakdown_value as "context.columns.breakdown_value",
        counts.total_pageviews as "context.columns.views",
        counts.unique_visitors as "context.columns.visitors",
        bounce_rate.bounce_rate as "context.columns.bounce_rate"
    FROM
        {counts_query} AS counts
    LEFT OUTER JOIN
        {bounce_rate_query} AS bounce_rate
    ON
        counts.breakdown_value = bounce_rate.breakdown_value
    WHERE
        {where_breakdown}
    ORDER BY
        "context.columns.views" DESC,
        "context.columns.breakdown_value" ASC
                    """,
                    timings=self.timings,
                    placeholders={
                        "counts_query": self._counts_subquery(),
                        "bounce_rate_query": self._bounce_rate_subquery(),
                        "where_breakdown": self.where_breakdown(),
                    },
                )
        else:
            with self.timings.measure("stats_table_query"):
                query = parse_select(
                    """
    SELECT
        counts.breakdown_value as "context.columns.breakdown_value",
        counts.total_pageviews as "context.columns.views",
        counts.unique_visitors as "context.columns.visitors"
    FROM
        {counts_query} AS counts
    WHERE
        {where_breakdown}
    ORDER BY
        "context.columns.views" DESC,
        "context.columns.breakdown_value" ASC
                    """,
                    timings=self.timings,
                    placeholders={
                        "counts_query": self._counts_subquery(),
                        "where_breakdown": self.where_breakdown(),
                    },
                )
        assert isinstance(query, ast.SelectQuery)
        return query

    def calculate(self):
        response = self.paginator.execute_hogql_query(
            query_type="top_sources_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        results = self.paginator.results

        assert results is not None

        results_mapped = map_columns(
            results,
            {
                1: self._unsample,  # views
                2: self._unsample,  # visitors
            },
        )

        return WebStatsTableQueryResponse(
            columns=response.columns,
            results=results_mapped,
            timings=response.timings,
            types=response.types,
            hogql=response.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def counts_breakdown(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.PAGE:
                return self._apply_path_cleaning(ast.Field(chain=["properties", "$pathname"]))
            case WebStatsBreakdown.INITIAL_CHANNEL_TYPE:
                raise NotImplementedError("Breakdown InitialChannelType not implemented")
            case WebStatsBreakdown.INITIAL_PAGE:
                return self._apply_path_cleaning(ast.Field(chain=["person", "properties", "$initial_pathname"]))
            case WebStatsBreakdown.INITIAL_REFERRING_DOMAIN:
                return ast.Field(chain=["person", "properties", "$initial_referring_domain"])
            case WebStatsBreakdown.INITIAL_UTM_SOURCE:
                return ast.Field(chain=["person", "properties", "$initial_utm_source"])
            case WebStatsBreakdown.INITIAL_UTM_CAMPAIGN:
                return ast.Field(chain=["person", "properties", "$initial_utm_campaign"])
            case WebStatsBreakdown.INITIAL_UTM_MEDIUM:
                return ast.Field(chain=["person", "properties", "$initial_utm_medium"])
            case WebStatsBreakdown.INITIAL_UTM_TERM:
                return ast.Field(chain=["person", "properties", "$initial_utm_term"])
            case WebStatsBreakdown.INITIAL_UTM_CONTENT:
                return ast.Field(chain=["person", "properties", "$initial_utm_content"])
            case WebStatsBreakdown.BROWSER:
                return ast.Field(chain=["properties", "$browser"])
            case WebStatsBreakdown.OS:
                return ast.Field(chain=["properties", "$os"])
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
            case _:
                raise NotImplementedError("Breakdown not implemented")

    def bounce_breakdown(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.PAGE:
                # use initial pathname for bounce rate
                return self._apply_path_cleaning(
                    ast.Call(name="any", args=[ast.Field(chain=["person", "properties", "$initial_pathname"])])
                )
            case WebStatsBreakdown.INITIAL_CHANNEL_TYPE:
                raise NotImplementedError("Breakdown InitialChannelType not implemented")
            case WebStatsBreakdown.INITIAL_PAGE:
                return self._apply_path_cleaning(
                    ast.Call(name="any", args=[ast.Field(chain=["person", "properties", "$initial_pathname"])])
                )
            case _:
                return ast.Call(name="any", args=[self.counts_breakdown()])

    def where_breakdown(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.REGION:
                return parse_expr('tupleElement("context.columns.breakdown_value", 2) IS NOT NULL')
            case WebStatsBreakdown.CITY:
                return parse_expr('tupleElement("context.columns.breakdown_value", 2) IS NOT NULL')
            case WebStatsBreakdown.INITIAL_CHANNEL_TYPE:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.INITIAL_UTM_SOURCE:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.INITIAL_UTM_CAMPAIGN:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.INITIAL_UTM_MEDIUM:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.INITIAL_UTM_TERM:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.INITIAL_UTM_CONTENT:
                return parse_expr("TRUE")  # actually show null values
            case _:
                return parse_expr('"context.columns.breakdown_value" IS NOT NULL')

    def to_channel_query(self):
        with self.timings.measure("channel_query"):
            top_sources_query = parse_select(
                """
SELECT
    counts.breakdown_value as "context.columns.breakdown_value",
    counts.total_pageviews as "context.columns.views",
    counts.unique_visitors as "context.columns.visitors"
FROM
    (SELECT


        {channel_type} AS breakdown_value,
        count() as total_pageviews,
        uniq(pid) as unique_visitors
    FROM
        (SELECT
            toString(person.properties.$initial_utm_campaign) AS initial_utm_campaign,
            toString(person.properties.$initial_utm_medium) AS initial_utm_medium,
            toString(person.properties.$initial_utm_source) AS initial_utm_source,
            toString(person.properties.$initial_referring_domain) AS initial_referring_domain,
            toString(person.properties.$initial_gclid) AS initial_gclid,
            toString(person.properties.$initial_gad_source) AS initial_gad_source,
            person_id AS pid
        FROM events
        SAMPLE {sample_rate}
        WHERE
            (event = '$pageview')
            AND ({counts_where})
        )

        GROUP BY breakdown_value
    ) AS counts
WHERE
    {where_breakdown}
ORDER BY
    "context.columns.views" DESC,
    "context.columns.breakdown_value" ASC
                """,
                timings=self.timings,
                backend="cpp",
                placeholders={
                    "counts_where": self.events_where(),
                    "where_breakdown": self.where_breakdown(),
                    "sample_rate": self._sample_ratio,
                    "channel_type": create_channel_type_expr(
                        campaign=ast.Call(name="toString", args=[ast.Field(chain=["initial_utm_campaign"])]),
                        medium=ast.Call(name="toString", args=[ast.Field(chain=["initial_utm_medium"])]),
                        source=ast.Call(name="toString", args=[ast.Field(chain=["initial_utm_source"])]),
                        referring_domain=ast.Call(
                            name="toString", args=[ast.Field(chain=["initial_referring_domain"])]
                        ),
                        gclid=ast.Call(name="toString", args=[ast.Field(chain=["initial_gclid"])]),
                        gad_source=ast.Call(name="toString", args=[ast.Field(chain=["initial_gad_source"])]),
                    ),
                },
            )

        return top_sources_query

    def _apply_path_cleaning(self, path_expr: ast.Expr) -> ast.Expr:
        if not self.query.doPathCleaning or not self.team.path_cleaning_filters:
            return path_expr

        for replacement in self.team.path_cleaning_filter_models():
            path_expr = ast.Call(
                name="replaceRegexpAll",
                args=[
                    path_expr,
                    ast.Constant(value=replacement.regex),
                    ast.Constant(value=replacement.alias),
                ],
            )

        return path_expr
