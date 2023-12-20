from typing import List, Any, Optional, cast, Sequence

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import HogQLQueryResponse


class HogQLHasMorePaginator:
    """
    Paginator that fetches one more result than requested to determine if there are more results.
    Takes care of setting the limit and offset on the query.
    """

    def __init__(self, limit: int, offset: int):
        self.response: Optional[HogQLQueryResponse] = None
        self.results: Sequence[Any] = []
        self.limit = limit
        self.offset = offset

    def paginate(self, query: ast.SelectQuery) -> ast.SelectQuery:
        query.limit = ast.Constant(value=self.limit + 1)
        query.offset = ast.Constant(value=self.offset or 0)
        return query

    def has_more(self) -> bool:
        if not self.response or not self.response.results:
            return False

        return len(self.response.results) > self.limit

    def trim_results(self) -> List[Any]:
        if not self.response or not self.response.results:
            return []

        if self.has_more():
            return self.response.results[:-1]

        return self.response.results

    def execute_hogql_query(
        self,
        query_type: str,
        query: ast.SelectQuery,
        **kwargs,
    ) -> HogQLQueryResponse:
        self.response = cast(
            HogQLQueryResponse,
            execute_hogql_query(
                query=self.paginate(query),
                query_type=query_type,
                **kwargs,
            ),
        )
        self.results = self.trim_results()
        return self.response

    def response_params(self):
        return {
            "hasMore": self.has_more(),
            "limit": self.limit,
            "offset": self.offset,
        }
