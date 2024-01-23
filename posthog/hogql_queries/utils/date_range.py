from typing import Optional
from posthog.hogql import ast
from posthog.hogql_queries.insights.query_context import QueryContext
from posthog.hogql_queries.utils.query_date_range import QueryDateRange


# TODO: Refactor QueryDateRange to conform to this wrapper, if we decide for the context / utils approach
class DateRange:
    context: QueryContext

    def __init__(
        self,
        context: QueryContext,
    ) -> None:
        self.context = context

        return

    def to_expr(self, field: Optional[ast.Field] = None) -> ast.Expr:
        team, query, now = self.context.team, self.context.query, self.context.now

        if not field:
            field = ast.Field(chain=["timestamp"])

        date_range = QueryDateRange(
            date_range=query.dateRange,
            team=team,
            interval=query.interval,
            now=now,
        )

        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=field,
                    right=ast.Constant(value=date_range.date_from()),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=field,
                    right=ast.Constant(value=date_range.date_to()),
                ),
            ]
        )
