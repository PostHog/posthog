from typing import List

from posthog.hogql import ast
from posthog.hogql_queries.insights.funnels.funnel import Funnel


class FunnelStrictActors(Funnel):
    def actor_query(
        self,
        # extra_fields: Optional[List[str]] = None,
    ) -> ast.SelectQuery:
        select: List[ast.Expr] = [
            ast.Alias(alias="actor_id", expr=ast.Field(chain=["aggregation_target"])),
            *self._get_funnel_person_step_events(),
            *self._get_timestamp_outer_select(),
            # {extra_fields}
        ]
        select_from = ast.JoinExpr(table=self.get_step_counts_query())
        where = self._get_funnel_person_step_condition()
        order_by = [ast.OrderExpr(expr=ast.Field(chain=["aggregation_target"]))]

        return ast.SelectQuery(
            select=select,
            select_from=select_from,
            order_by=order_by,
            where=where,
            # SETTINGS max_ast_elements=1000000, max_expanded_ast_elements=1000000
        )
