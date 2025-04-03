from typing import Optional, Any, cast, Union
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
)
from posthog.schema import (
    WebAnalyticsPageURLSearchQuery,
    WebAnalyticsPageURLSearchQueryResponse,
    CachedWebAnalyticsPageURLSearchQueryResponse,
    PageURL,
    HogQLQueryModifiers,
)
from posthog.models import Team
from posthog.hogql.constants import LimitContext
from posthog.api.services.query import process_query_dict


class PageUrlSearchQueryRunner(WebAnalyticsQueryRunner):
    query: WebAnalyticsPageURLSearchQuery  # Type will be overridden in the init
    response: WebAnalyticsPageURLSearchQueryResponse
    cached_response: CachedWebAnalyticsPageURLSearchQueryResponse

    def __init__(
        self,
        query: Union[dict[str, Any], WebAnalyticsPageURLSearchQuery],
        team: Team,
        timings=None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        if not isinstance(query, WebAnalyticsPageURLSearchQuery):
            query = process_query_dict(query, WebAnalyticsPageURLSearchQuery)
        super().__init__(query=query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

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

    def calculate(self) -> WebAnalyticsPageURLSearchQueryResponse:
        query = self._get_hogql_query()
        limit = self.query.limit or 100

        modifiers_dict = self.modifiers.model_dump() if self.modifiers else {"cache": True, "cache_ttl": 300}

        response = execute_hogql_query(
            query=query,
            team=self.team,
            query_type="WebAnalyticsPageURLSearch",
            context=HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                timings=self.timings,
                modifiers=cast(HogQLQueryModifiers, modifiers_dict),
            ),
            limit_context=self.limit_context,
        )

        results = []
        for row in response.results:
            results.append(PageURL(url=str(row[0]), count=float(row[1])))

        return WebAnalyticsPageURLSearchQueryResponse(
            results=results,
            timings=response.timings,
            hasMore=len(response.results) >= limit,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
