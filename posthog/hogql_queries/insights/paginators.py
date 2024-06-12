from typing import Any, Optional, cast

from posthog.hogql import ast
from posthog.hogql.constants import (
    get_max_limit_for_context,
    get_default_limit_for_context,
    LimitContext,
    DEFAULT_RETURNED_ROWS,
)
from posthog.hogql.query import execute_hogql_query
from posthog.schema import HogQLQueryResponse


class HogQLHasMorePaginator:
    """
    Paginator that fetches one more result than requested to determine if there are more results.
    Takes care of setting the limit and offset on the query.
    """

    def __init__(
        self, *, limit: Optional[int] = None, offset: Optional[int] = None, limit_context: Optional[LimitContext] = None
    ):
        self.response: Optional[HogQLQueryResponse] = None
        self.results: list[Any] = []
        self.limit = limit if limit and limit > 0 else DEFAULT_RETURNED_ROWS
        self.offset = offset if offset and offset > 0 else 0
        self.limit_context = limit_context

    @classmethod
    def from_limit_context(
        cls, *, limit_context: LimitContext, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> "HogQLHasMorePaginator":
        max_rows = get_max_limit_for_context(limit_context)
        default_rows = get_default_limit_for_context(limit_context)
        limit = min(max_rows, default_rows if (limit is None or limit <= 0) else limit)
        return cls(limit=limit, offset=offset, limit_context=limit_context)

    def paginate(self, query: ast.SelectQuery) -> ast.SelectQuery:
        query.limit = ast.Constant(value=self.limit + 1)
        query.offset = ast.Constant(value=self.offset)
        return query

    def has_more(self) -> bool:
        if not self.response or not self.response.results:
            return False

        return len(self.response.results) > self.limit

    def trim_results(self) -> list[Any]:
        if not self.response or not self.response.results:
            return []

        if self.has_more():
            return self.response.results[:-1]

        return self.response.results

    def execute_hogql_query(
        self,
        query: ast.SelectQuery,
        *,
        query_type: str,
        **kwargs,
    ) -> HogQLQueryResponse:
        self.response = cast(
            HogQLQueryResponse,
            execute_hogql_query(
                query=self.paginate(query),
                query_type=query_type,
                **kwargs if self.limit_context is None else {"limit_context": self.limit_context, **kwargs},
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
