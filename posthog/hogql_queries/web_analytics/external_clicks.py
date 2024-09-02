from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.property import (
    property_to_expr,
)
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
    map_columns,
)
from posthog.schema import (
    CachedWebStatsTableQueryResponse,
    WebStatsTableQueryResponse,
    WebExternalClicksTableQuery,
    WebExternalClicksTableQueryResponse,
)


class WebExternalClicksTableQueryRunner(WebAnalyticsQueryRunner):
    query: WebExternalClicksTableQuery
    response: WebExternalClicksTableQueryResponse
    cached_response: CachedWebStatsTableQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY, limit=self.query.limit if self.query.limit else None
        )

    def to_query(self) -> ast.SelectQuery:
        if self.query.stripQueryParams:
            url_expr = ast.Call(
                name="cutQueryStringAndFragment",
                args=[ast.Field(chain=["properties", "$external_click_url"])],
            )
        else:
            url_expr = ast.Field(chain=["properties", "$external_click_url"])

        with self.timings.measure("stats_table_query"):
            query = parse_select(
                """
SELECT
    url AS "context.columns.url",
    uniq(filtered_person_id) AS "context.columns.visitors",
    sum(filtered_click_count) AS "context.columns.clicks"
FROM (
    SELECT
        any(person_id) AS filtered_person_id,
        count() AS filtered_click_count,
        {url_expr} AS url
    FROM events
    WHERE and(
        timestamp >= {date_from},
        timestamp < {date_to},
        events.event == '$autocapture',
        events.properties.$event_type == 'click',
        url IS NOT NULL,
        url != '',
        {all_properties}
    )
    GROUP BY events.`$session_id`, url
)
GROUP BY "context.columns.url"
ORDER BY "context.columns.visitors" DESC,
"context.columns.url" ASC
""",
                timings=self.timings,
                placeholders={
                    "url_expr": url_expr,
                    "all_properties": self._all_properties(),
                    "date_from": self._date_from(),
                    "date_to": self._date_to(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _all_properties(self) -> ast.Expr:
        properties = self.query.properties + self._test_account_filters
        return property_to_expr(properties, team=self.team)

    def _date_to(self) -> ast.Expr:
        return self.query_date_range.date_to_as_hogql()

    def _date_from(self) -> ast.Expr:
        return self.query_date_range.date_from_as_hogql()

    def calculate(self):
        query = self.to_query()
        response = self.paginator.execute_hogql_query(
            query_type="stats_table_query",
            query=query,
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
