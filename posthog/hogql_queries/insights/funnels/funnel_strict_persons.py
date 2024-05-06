from typing import Optional

from posthog.hogql import ast
from posthog.hogql_queries.insights.funnels.funnel_strict import FunnelStrict


class FunnelStrictActors(FunnelStrict):
    def actor_query(
        self,
        extra_fields: Optional[list[str]] = None,
    ) -> ast.SelectQuery:
        select: list[ast.Expr] = [
            ast.Alias(alias="actor_id", expr=ast.Field(chain=["aggregation_target"])),
            *self._get_funnel_person_step_events(),
            *self._get_timestamp_outer_select(),
            *([ast.Field(chain=[field]) for field in extra_fields or []]),
        ]
        select_from = ast.JoinExpr(table=self.get_step_counts_query())
        where = self._get_funnel_person_step_condition()
        order_by = [ast.OrderExpr(expr=ast.Field(chain=["aggregation_target"]))]

        return ast.SelectQuery(
            select=select,
            select_from=select_from,
            order_by=order_by,
            where=where,
        )
