from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select, parse_expr
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.web_analytics.ctes import (
    COUNTS_CTE,
    BOUNCE_RATE_CTE,
    PATHNAME_SCROLL_CTE,
)
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
)
from posthog.schema import (
    WebStatsTableQuery,
    WebStatsBreakdown,
    WebStatsTableQueryResponse,
)


class WebStatsTableQueryRunner(WebAnalyticsQueryRunner):
    query: WebStatsTableQuery
    query_type = WebStatsTableQuery
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY, limit=self.query.limit
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

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        # special case for channel, as some hogql features to use the general code are still being worked on
        if self.query.breakdownBy == WebStatsBreakdown.InitialChannelType:
            return self.to_channel_query()

        if self.query.includeScrollDepth:
            return parse_select(
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
    "context.columns.breakdown_value" DESC
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
                return parse_select(
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
        "context.columns.breakdown_value" DESC
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
                return parse_select(
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
        "context.columns.breakdown_value" DESC
                    """,
                    timings=self.timings,
                    placeholders={
                        "counts_query": self._counts_subquery(),
                        "where_breakdown": self.where_breakdown(),
                    },
                )

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

        def to_data(col_val, col_idx):
            if col_idx == 0:  # breakdown_value
                return col_val
            elif col_idx == 1:  # views
                return self._unsample(col_val)
            elif col_idx == 2:  # visitors
                return self._unsample(col_val)
            elif col_idx == 3:  # bounce_rate
                return col_val
            else:
                return col_val

        results_mapped = [[to_data(c, i) for (i, c) in enumerate(r)] for r in results]

        return WebStatsTableQueryResponse(
            columns=response.columns,
            results=results_mapped,
            timings=response.timings,
            types=response.types,
            hogql=response.hogql,
            hasMore=self.paginator.has_more(),
        )

    def counts_breakdown(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.Page:
                return ast.Field(chain=["properties", "$pathname"])
            case WebStatsBreakdown.InitialChannelType:
                raise NotImplementedError("Breakdown InitialChannelType not implemented")
            case WebStatsBreakdown.InitialPage:
                return ast.Field(chain=["person", "properties", "$initial_pathname"])
            case WebStatsBreakdown.InitialReferringDomain:
                return ast.Field(chain=["person", "properties", "$initial_referring_domain"])
            case WebStatsBreakdown.InitialUTMSource:
                return ast.Field(chain=["person", "properties", "$initial_utm_source"])
            case WebStatsBreakdown.InitialUTMCampaign:
                return ast.Field(chain=["person", "properties", "$initial_utm_campaign"])
            case WebStatsBreakdown.InitialUTMMedium:
                return ast.Field(chain=["person", "properties", "$initial_utm_medium"])
            case WebStatsBreakdown.InitialUTMTerm:
                return ast.Field(chain=["person", "properties", "$initial_utm_term"])
            case WebStatsBreakdown.InitialUTMContent:
                return ast.Field(chain=["person", "properties", "$initial_utm_content"])
            case WebStatsBreakdown.Browser:
                return ast.Field(chain=["properties", "$browser"])
            case WebStatsBreakdown.OS:
                return ast.Field(chain=["properties", "$os"])
            case WebStatsBreakdown.DeviceType:
                return ast.Field(chain=["properties", "$device_type"])
            case WebStatsBreakdown.Country:
                return ast.Field(chain=["properties", "$geoip_country_code"])
            case WebStatsBreakdown.Region:
                return parse_expr(
                    "tuple(properties.$geoip_country_code, properties.$geoip_subdivision_1_code, properties.$geoip_subdivision_1_name)"
                )
            case WebStatsBreakdown.City:
                return parse_expr("tuple(properties.$geoip_country_code, properties.$geoip_city_name)")
            case _:
                raise NotImplementedError("Breakdown not implemented")

    def bounce_breakdown(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.Page:
                # use initial pathname for bounce rate
                return ast.Call(name="any", args=[ast.Field(chain=["person", "properties", "$initial_pathname"])])
            case WebStatsBreakdown.InitialChannelType:
                raise NotImplementedError("Breakdown InitialChannelType not implemented")
            case _:
                return ast.Call(name="any", args=[self.counts_breakdown()])

    def where_breakdown(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.Region:
                return parse_expr('tupleElement("context.columns.breakdown_value", 2) IS NOT NULL')
            case WebStatsBreakdown.City:
                return parse_expr('tupleElement("context.columns.breakdown_value", 2) IS NOT NULL')
            case WebStatsBreakdown.InitialChannelType:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.InitialUTMSource:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.InitialUTMCampaign:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.InitialUTMMedium:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.InitialUTMTerm:
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.InitialUTMContent:
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


        multiIf(
            match(initial_utm_campaign, 'cross-network'),
            'Cross Network',

            (
                match(initial_utm_medium, '^(.*cp.*|ppc|retargeting|paid.*)$') OR
                initial_gclid IS NOT NULL OR
                initial_gad_source IS NOT NULL
            ),
            coalesce(
                hogql_lookupPaidSourceType(initial_utm_source),
                hogql_lookupPaidDomainType(initial_referring_domain),
                if(
                    match(initial_utm_campaign, '^(.*(([^a-df-z]|^)shop|shopping).*)$'),
                    'Paid Shopping',
                    NULL
                ),
                hogql_lookupPaidMediumType(initial_utm_medium),
                multiIf (
                    initial_gad_source = '1',
                    'Paid Search',

                    match(initial_utm_campaign, '^(.*video.*)$'),
                    'Paid Video',

                    'Paid Other'
                )
            ),

            (
                initial_referring_domain = '$direct'
                AND (initial_utm_medium IS NULL OR initial_utm_medium = '')
                AND (initial_utm_source IS NULL OR initial_utm_source IN ('', '(direct)', 'direct'))
            ),
            'Direct',

            coalesce(
                hogql_lookupOrganicSourceType(initial_utm_source),
                hogql_lookupOrganicDomainType(initial_referring_domain),
                if(
                    match(initial_utm_campaign, '^(.*(([^a-df-z]|^)shop|shopping).*)$'),
                    'Organic Shopping',
                    NULL
                ),
                hogql_lookupOrganicMediumType(initial_utm_medium),
                multiIf(
                    match(initial_utm_campaign, '^(.*video.*)$'),
                    'Organic Video',

                    match(initial_utm_medium, 'push$'),
                    'Push',

                    'Other'
                )
            )
        ) AS breakdown_value,
        count() as total_pageviews,
        uniq(pid) as unique_visitors
    FROM
        (SELECT
            person.properties.$initial_utm_campaign AS initial_utm_campaign,
            person.properties.$initial_utm_medium AS initial_utm_medium,
            person.properties.$initial_utm_source AS initial_utm_source,
            person.properties.$initial_referring_domain AS initial_referring_domain,
            person.properties.$initial_gclid AS initial_gclid,
            person.properties.$initial_gad_source AS initial_gad_source,
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
    "context.columns.breakdown_value" DESC
                """,
                timings=self.timings,
                backend="cpp",
                placeholders={
                    "counts_where": self.events_where(),
                    "where_breakdown": self.where_breakdown(),
                    "sample_rate": self._sample_ratio,
                },
            )

        return top_sources_query
