import json
import base64
from datetime import datetime
from typing import Any, Union, cast

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
        self, *, limit: int | None = None, offset: int | None = None, limit_context: LimitContext | None = None
    ):
        self.response: HogQLQueryResponse | None = None
        self.results: list[Any] = []
        self.limit = limit if limit and limit > 0 else DEFAULT_RETURNED_ROWS
        self.offset = offset if offset and offset > 0 else 0
        self.limit_context = limit_context

    @classmethod
    def from_limit_context(
        cls, *, limit_context: LimitContext, limit: int | None = None, offset: int | None = None
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


class HogQLCursorPaginator:
    """
    Cursor-based paginator for timestamp-based pagination.
    Uses a cursor containing the ordering value and a secondary field from the last record.
    This is more efficient than offset-based pagination for large datasets.
    """

    def __init__(
        self,
        *,
        limit: int | None = None,
        after: str | None = None,
        order_field: str = "start_time",
        order_direction: str = "DESC",
        secondary_sort_field: str,
        limit_context: LimitContext | None = None,
        field_indices: dict[str, int] | None = None,
        use_having_clause: bool = False,
    ):
        self.response: HogQLQueryResponse | None = None
        self.results: list[Any] = []
        self.limit = limit if limit and limit > 0 else DEFAULT_RETURNED_ROWS
        self.after = after
        self.order_field = order_field
        self.order_direction = order_direction
        self.secondary_sort_field = secondary_sort_field
        self.limit_context = limit_context
        self.field_indices = field_indices or {}
        self.use_having_clause = use_having_clause
        self.cursor_data: dict[str, Any] | None = None

        if self.after:
            try:
                decoded = base64.b64decode(self.after).decode("utf-8")
                cursor_data = json.loads(decoded)
                # Parse datetime strings back to datetime objects
                if "order_value" in cursor_data and isinstance(cursor_data["order_value"], str):
                    try:
                        cursor_data["order_value"] = datetime.fromisoformat(cursor_data["order_value"])
                    except (ValueError, TypeError):
                        # If it's not a datetime string, keep it as is
                        pass
                self.cursor_data = cursor_data
            except (ValueError, json.JSONDecodeError):
                raise ValueError("Invalid cursor format")

    @classmethod
    def from_limit_context(
        cls,
        *,
        limit_context: LimitContext,
        limit: int | None = None,
        after: str | None = None,
        order_field: str = "start_time",
        order_direction: str = "DESC",
        secondary_sort_field: str,
        field_indices: dict[str, int] | None = None,
        use_having_clause: bool = False,
    ) -> "HogQLCursorPaginator":
        max_rows = get_max_limit_for_context(limit_context)
        default_rows = get_default_limit_for_context(limit_context)
        limit = min(max_rows, default_rows if (limit is None or limit <= 0) else limit)
        return cls(
            limit=limit,
            after=after,
            order_field=order_field,
            order_direction=order_direction,
            secondary_sort_field=secondary_sort_field,
            limit_context=limit_context,
            field_indices=field_indices,
            use_having_clause=use_having_clause,
        )

    def paginate(self, query: Union[ast.SelectQuery, ast.SelectSetQuery]) -> Union[ast.SelectQuery, ast.SelectSetQuery]:
        if isinstance(query, ast.SelectQuery):
            query.limit = ast.Constant(value=self.limit + 1)

            if self.cursor_data:
                order_value = self.cursor_data.get("order_value")
                # TODO: Remove session_id fallback after Jan 2026
                # only needed for cursors created before the secondary_value rename
                secondary_value = self.cursor_data.get("secondary_value") or self.cursor_data.get("session_id")

                if order_value is not None and secondary_value is not None:
                    # Build WHERE clause for cursor-based pagination
                    # For DESC: WHERE (order_field, secondary_field) < (cursor_value, cursor_secondary_value)
                    # For ASC: WHERE (order_field, secondary_field) > (cursor_value, cursor_secondary_value)

                    # Create tuple comparison expression
                    left_tuple = ast.Tuple(
                        exprs=[
                            ast.Field(chain=[self.order_field]),
                            ast.Field(chain=[self.secondary_sort_field]),
                        ]
                    )

                    right_tuple = ast.Tuple(
                        exprs=[
                            ast.Constant(value=order_value),
                            ast.Constant(value=secondary_value),
                        ]
                    )

                    comparison_op = (
                        ast.CompareOperationOp.Lt if self.order_direction == "DESC" else ast.CompareOperationOp.Gt
                    )

                    cursor_condition = ast.CompareOperation(
                        left=left_tuple,
                        op=comparison_op,
                        right=right_tuple,
                    )

                    # Add to HAVING clause for aggregated queries, WHERE clause for non-aggregated
                    if self.use_having_clause:
                        if query.having:
                            query.having = ast.And(exprs=[query.having, cursor_condition])
                        else:
                            query.having = cursor_condition
                    else:
                        if query.where:
                            query.where = ast.And(exprs=[query.where, cursor_condition])
                        else:
                            query.where = cursor_condition

            return query
        elif isinstance(query, ast.SelectSetQuery):
            for select_query in query.select_queries():
                self.paginate(select_query)
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

    def get_next_cursor(self) -> str | None:
        """
        Generate cursor for the next page based on the last result.
        Returns None if there are no more results.
        """
        if not self.has_more() or not self.results:
            return None

        # Get the last result
        last_result = self.results[-1]

        # Extract the ordering value and secondary field value
        # Handle different result types: dict (from HogQL), tuple, or object
        if isinstance(last_result, dict):
            order_value = last_result.get(self.order_field)
            secondary_value = last_result.get(self.secondary_sort_field)
        elif isinstance(last_result, list | tuple) and self.field_indices:
            # For tuples, use field_indices to find the correct position
            order_idx = self.field_indices.get(self.order_field)
            secondary_idx = self.field_indices.get(self.secondary_sort_field, 0)
            order_value = last_result[order_idx] if order_idx is not None else None
            secondary_value = last_result[secondary_idx]
        else:
            # For objects, use getattr
            order_value = getattr(last_result, self.order_field, None)
            secondary_value = getattr(last_result, self.secondary_sort_field, None)

        # Serialize datetime objects to ISO format strings
        if isinstance(order_value, datetime):
            order_value = order_value.isoformat()

        cursor_data = {
            "order_value": order_value,
            "secondary_value": secondary_value,
        }

        # Encode as base64
        json_str = json.dumps(cursor_data)
        return base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

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
            "nextCursor": self.get_next_cursor(),
        }
