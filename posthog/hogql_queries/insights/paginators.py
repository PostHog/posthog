from typing import Any, Optional, Union, cast

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.constants import (
    DEFAULT_RETURNED_ROWS,
    LimitContext,
    get_default_limit_for_context,
    get_max_limit_for_context,
)
from posthog.hogql.query import execute_hogql_query


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

    def paginate(self, query: Union[ast.SelectQuery, ast.SelectSetQuery]) -> Union[ast.SelectQuery, ast.SelectSetQuery]:
        if isinstance(query, ast.SelectQuery):
            query.limit = ast.Constant(value=self.limit + 1)
            query.offset = ast.Constant(value=self.offset)
            return query
        elif isinstance(query, ast.SelectSetQuery):
            # Doesn't really make sense to paginate a SelectSetQuery, but we can paginate each of the individual select queries
            # Note that simply dividing the limit by the number of queries doesn't work because the offset needs to be applied
            # to each query individually.
            for select_query in query.select_queries():
                self.paginate(select_query)  # Updates in place
            return query

        raise ValueError(f"Unsupported query type: {type(query)}, must be one of SELECT type")

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
        query: Union[ast.SelectQuery, ast.SelectSetQuery],
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
