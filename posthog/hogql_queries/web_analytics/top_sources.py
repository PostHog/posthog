from django.utils.timezone import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import WebTopSourcesQuery, WebTopSourcesQueryResponse


class WebTopSourcesQueryRunner(WebAnalyticsQueryRunner):
    query: WebTopSourcesQuery
    query_type = WebTopSourcesQuery

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("top_sources_query"):
            top_sources_query = parse_select(
                """
WITH

session_cte AS (
SELECT
    events.properties.`$session_id` AS session_id,
    min(events.timestamp) AS min_timestamp,
    max(events.timestamp) AS max_timestamp,
    dateDiff('second', min_timestamp, max_timestamp) AS duration_s,

    -- create a tuple so that these are grouped in the same order, see https://github.com/ClickHouse/ClickHouse/discussions/42338
    groupArray((events.timestamp, events.properties.`$referrer`, events.properties.`$pathname`, events.properties.utm_source)) AS tuple_array,
    arrayFirstIndex(x -> tupleElement(x, 1) == min_timestamp, tuple_array) as index_of_earliest,
    arrayFirstIndex(x -> tupleElement(x, 1) == max_timestamp, tuple_array) as index_of_latest,
    tupleElement(arrayElement(
        tuple_array,
        index_of_earliest
    ), 2) AS earliest_referrer,
    tupleElement(arrayElement(
        tuple_array,
        index_of_earliest
    ), 3) AS earliest_pathname,
    tupleElement(arrayElement(
        tuple_array,
        index_of_earliest
    ), 4) AS earliest_utm_source,

    if(domain(earliest_referrer) = '', earliest_referrer, domain(earliest_referrer)) AS referrer_domain,
    multiIf(
        earliest_utm_source IS NOT NULL, earliest_utm_source,
        -- This will need to be an approach that scales better
        referrer_domain == 'app.posthog.com', 'posthog',
        referrer_domain == 'eu.posthog.com', 'posthog',
        referrer_domain == 'posthog.com', 'posthog',
        referrer_domain == 'www.google.com', 'google',
        referrer_domain == 'www.google.co.uk', 'google',
        referrer_domain == 'www.google.com.hk', 'google',
        referrer_domain == 'www.google.de', 'google',
        referrer_domain == 't.co', 'twitter',
        referrer_domain == 'github.com', 'github',
        referrer_domain == 'duckduckgo.com', 'duckduckgo',
        referrer_domain == 'www.bing.com', 'bing',
        referrer_domain == 'bing.com', 'bing',
        referrer_domain == 'yandex.ru', 'yandex',
        referrer_domain == 'quora.com', 'quora',
        referrer_domain == 'www.quora.com', 'quora',
        referrer_domain == 'linkedin.com', 'linkedin',
        referrer_domain == 'www.linkedin.com', 'linkedin',
        startsWith(referrer_domain, 'http://localhost:'), 'localhost',
        referrer_domain
    ) AS blended_source,

    countIf(events.event == '$pageview') AS num_pageviews,
    countIf(events.event == '$autocapture') AS num_autocaptures,
    -- in v1 we'd also want to count whether there were any conversion events

    any(events.person_id) as person_id,
    -- definition of a GA4 bounce from here https://support.google.com/analytics/answer/12195621?hl=en
    (num_autocaptures == 0 AND num_pageviews <= 1 AND duration_s < 10) AS is_bounce
FROM
    events
WHERE
    session_id IS NOT NULL
AND
    events.timestamp >= now() - INTERVAL 8 DAY
GROUP BY
    events.properties.`$session_id`
HAVING
    min_timestamp >= now() - INTERVAL 7 DAY
)



SELECT
    blended_source,
    count(num_pageviews) as total_pageviews,
    count(DISTINCT person_id) as unique_visitors,
    avg(is_bounce) AS bounce_rate
FROM
    session_cte
WHERE
    blended_source IS NOT NULL
GROUP BY blended_source

ORDER BY total_pageviews DESC
LIMIT 100
                """,
                timings=self.timings,
            )
        return top_sources_query

    def calculate(self):
        response = execute_hogql_query(
            query_type="top_sources_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
        )

        return WebTopSourcesQueryResponse(
            columns=response.columns, result=response.results, timings=response.timings, types=response.types
        )

    @cached_property
    def query_date_range(self):
        return QueryDateRange(date_range=self.query.dateRange, team=self.team, interval=None, now=datetime.now())
