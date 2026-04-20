from posthog.schema import (
    CachedWebPageURLSearchQueryResponse,
    PageURL,
    WebPageURLSearchQuery,
    WebPageURLSearchQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner

PAGE_URL_SEARCH_DEFAULT_LIMIT = 100


class PageUrlSearchQueryRunner(WebAnalyticsQueryRunner[WebPageURLSearchQueryResponse]):
    query: WebPageURLSearchQuery
    cached_response: CachedWebPageURLSearchQueryResponse

    def _get_url_column(self) -> ast.Expr:
        current_url = ast.Call(name="toString", args=[ast.Field(chain=["properties", "$current_url"])])

        if self.query.stripQueryParams:
            return ast.Call(name="cutQueryStringAndFragment", args=[current_url])
        else:
            return current_url

    def _get_search_condition(self) -> ast.Expr:
        if self.query.searchTerm:
            return ast.CompareOperation(
                left=ast.Call(name="toString", args=[ast.Field(chain=["properties", "$current_url"])]),
                op=ast.CompareOperationOp.ILike,
                right=ast.Constant(value=f"%{self.query.searchTerm}%"),
            )
        return ast.Constant(value=True)

    def to_query(self) -> ast.SelectQuery:
        return self._get_hogql_query()

    def _get_hogql_query(self) -> ast.SelectQuery:
        with self.timings.measure("page_url_search_query"):
            url_column = self._get_url_column()
            search_condition = self._get_search_condition()
            sampling_factor = self._sample_ratio
            limit = self.query.limit or PAGE_URL_SEARCH_DEFAULT_LIMIT

            where_exprs = [
                ast.CompareOperation(
                    left=ast.Field(chain=["event"]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value="$pageview"),
                ),
                search_condition,
                self._current_period_expression(field="timestamp"),
            ]

            select_query = ast.SelectQuery(
                select=[
                    ast.Alias(alias="url", expr=url_column),
                ],
                distinct=True,
                select_from=ast.JoinExpr(
                    table=ast.Field(chain=["events"]),
                    sample=ast.SampleExpr(sample_value=sampling_factor),
                ),
                where=ast.And(exprs=where_exprs),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["url"]), order="ASC")],
                limit=ast.Constant(value=limit),
            )

            return select_query

    def _calculate(self) -> WebPageURLSearchQueryResponse:
        query = self._get_hogql_query()
        limit = self.query.limit or PAGE_URL_SEARCH_DEFAULT_LIMIT

        response = execute_hogql_query(
            query=query,
            team=self.team,
            query_type="WebAnalyticsPageURLSearch",
            context=HogQLContext(
                team_id=self.team.pk,
                timings=self.timings,
                modifiers=self.modifiers,
            ),
            limit_context=self.limit_context,
        )

        results = [PageURL(url=str(row[0]) if row[0] is not None else "") for row in response.results]

        return WebPageURLSearchQueryResponse(
            results=results,
            timings=response.timings,
            hasMore=len(response.results) >= limit,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
