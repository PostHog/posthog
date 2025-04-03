from typing import cast
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
)
from posthog.schema import (
    WebPageURLSearchQuery,
    WebPageURLSearchQueryResponse,
    CachedWebPageURLSearchQueryResponse,
    PageURL,
    HogQLQueryModifiers,
)


class PageUrlSearchQueryRunner(WebAnalyticsQueryRunner):
    query: WebPageURLSearchQuery
    response: WebPageURLSearchQueryResponse
    cached_response: CachedWebPageURLSearchQueryResponse

    def _get_url_column(self) -> str:
        return (
            f"cutQueryStringAndFragment(toString(properties.$current_url))"
            if self.query.strip_query_params
            else "toString(properties.$current_url)"
        )

    def _get_search_condition(self) -> str:
        if self.query.search_term:
            return f"toString(properties.$current_url) ILIKE '%{self.query.search_term}%'"
        return "1=1"

    def to_query(self) -> ast.SelectQuery:
        return self._get_hogql_query()

    def _get_hogql_query(self) -> ast.SelectQuery:
        with self.timings.measure("page_url_search_query"):
            url_column = self._get_url_column()
            search_condition = self._get_search_condition()
            sampling_factor = self.query.sampling_factor or 0.1
            limit = self.query.limit or 100

            query = parse_select(
                f"""
                SELECT DISTINCT {url_column} AS url, count() as count
                FROM events SAMPLE {sampling_factor}
                WHERE event = '$pageview'
                    AND {search_condition}
                GROUP BY url
                ORDER BY count DESC
                LIMIT {limit}
            """,
                timings=self.timings,
            )

            return cast(ast.SelectQuery, query)

    def calculate(self) -> WebPageURLSearchQueryResponse:
        query = self._get_hogql_query()
        limit = self.query.limit or 100

        response = execute_hogql_query(
            query=query,
            team=self.team,
            query_type="WebAnalyticsPageURLSearch",
            context=HogQLContext(
                team_id=self.team.pk,
                timings=self.timings,
                modifiers=cast(HogQLQueryModifiers, self.modifiers.model_dump() if self.modifiers else {}),
            ),
            limit_context=self.limit_context,
        )

        results = []
        for row in response.results:
            results.append(PageURL(url=str(row[0]), count=float(row[1])))

        return WebPageURLSearchQueryResponse(
            results=results,
            timings=response.timings,
            hasMore=len(response.results) >= limit,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
