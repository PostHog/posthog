from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
)
from posthog.schema import (
    WebPageURLSearchQuery,
    WebPageURLSearchQueryResponse,
    CachedWebPageURLSearchQueryResponse,
    PageURL,
)


class PageUrlSearchQueryRunner(WebAnalyticsQueryRunner):
    query: WebPageURLSearchQuery
    response: WebPageURLSearchQueryResponse
    cached_response: CachedWebPageURLSearchQueryResponse

    def _get_url_column(self) -> ast.Expr:
        current_url = ast.Call(name="toString", args=[ast.Field(chain=["properties", "$current_url"])])

        if self.query.strip_query_params:
            return ast.Call(name="cutQueryStringAndFragment", args=[current_url])
        else:
            return current_url

    def _get_search_condition(self) -> ast.Expr:
        if self.query.search_term:
            return ast.CompareOperation(
                left=ast.Call(name="toString", args=[ast.Field(chain=["properties", "$current_url"])]),
                op=ast.CompareOperationOp.ILike,
                right=ast.Constant(value=f"%{self.query.search_term}%"),
            )
        return ast.Constant(value=True)

    def to_query(self) -> ast.SelectQuery:
        return self._get_hogql_query()

    def _get_hogql_query(self) -> ast.SelectQuery:
        with self.timings.measure("page_url_search_query"):
            url_column = self._get_url_column()
            search_condition = self._get_search_condition()
            sampling_factor = self.query.sampling_factor or 0.1
            limit = self.query.limit or 100

            select_query = ast.SelectQuery(
                select=[
                    ast.Alias(alias="url", expr=url_column),
                    ast.Alias(alias="count", expr=ast.Call(name="count", args=[])),
                ],
                distinct=True,
                select_from=ast.JoinExpr(
                    table=ast.Field(chain=["events"]),
                    sample=ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=sampling_factor))),
                ),
                where=ast.And(
                    exprs=[
                        ast.CompareOperation(
                            left=ast.Field(chain=["event"]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Constant(value="$pageview"),
                        ),
                        search_condition,
                    ]
                ),
                group_by=[ast.Field(chain=["url"])],
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["count"]), order="DESC")],
                limit=ast.Constant(value=limit),
            )

            return select_query

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
                modifiers=self.modifiers,
            ),
            limit_context=self.limit_context,
        )

        results = [PageURL(url=str(row[0]), count=int(row[1])) for row in response.results]

        return WebPageURLSearchQueryResponse(
            results=results,
            timings=response.timings,
            hasMore=len(response.results) >= limit,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
