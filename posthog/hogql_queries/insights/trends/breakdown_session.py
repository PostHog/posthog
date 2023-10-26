from typing import List
from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.utils.query_date_range import QueryDateRange


class BreakdownSession:
    query_date_range: QueryDateRange

    def __init__(self, query_date_range: QueryDateRange):
        self.query_date_range = query_date_range

    def session_inner_join(self) -> ast.JoinExpr:
        join = ast.JoinExpr(
            table=ast.Field(chain=["events"]),
            alias="e",
            next_join=ast.JoinExpr(
                join_type="INNER JOIN",
                alias="sessions",
                table=self._session_select_query(),
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        left=ast.Field(chain=["sessions", "$session_id"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Field(chain=["e", "$session_id"]),
                    )
                ),
            ),
        )

        return join

    def session_duration_property_chain(self) -> List[str]:
        return ["sessions", "session_duration"]

    def session_duration_field(self) -> ast.Field:
        return ast.Field(chain=self.session_duration_property_chain())

    def _session_select_query(self) -> ast.SelectQuery:
        return parse_select(
            """
                SELECT
                    "$session_id", dateDiff('second', min(timestamp), max(timestamp)) as session_duration
                FROM events
                WHERE
                    "$session_id" != '' AND
                    timestamp >= {date_from} - INTERVAL 24 HOUR AND
                    timestamp <= {date_to} + INTERVAL 24 HOUR
                GROUP BY "$session_id"
            """,
            placeholders=self.query_date_range.to_placeholders(),
        )
