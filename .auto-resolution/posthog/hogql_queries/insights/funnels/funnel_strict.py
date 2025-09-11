from posthog.schema import BreakdownType

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.insights.funnels.base import FunnelBase


class FunnelStrict(FunnelBase):
    def get_query(self):
        max_steps = self.context.max_steps

        if self.context.breakdown and self.context.breakdownType in [
            BreakdownType.PERSON,
            BreakdownType.EVENT,
            BreakdownType.GROUP,
        ]:
            return self._breakdown_other_subquery()

        select: list[ast.Expr] = [
            *self._get_count_columns(max_steps),
            *self._get_step_time_avgs(max_steps),
            *self._get_step_time_median(max_steps),
            *self._get_breakdown_prop_expr(),
        ]

        select_query = ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=self.get_step_counts_query()),
            group_by=self._get_breakdown_prop_expr(),
        )
        return select_query

    def get_step_counts_query(self):
        max_steps = self.context.max_steps
        return self._get_step_counts_query(
            outer_select=[
                *self._get_matching_event_arrays(max_steps),
            ],
            inner_select=[
                *self._get_matching_events(max_steps),
            ],
        )

    def get_step_counts_without_aggregation_query(self):
        max_steps = self.context.max_steps

        select_inner: list[ast.Expr] = [
            ast.Field(chain=["aggregation_target"]),
            ast.Field(chain=["timestamp"]),
            *self._get_partition_cols(1, max_steps),
            *self._get_breakdown_prop_expr(group_remaining=True),
            *self._get_person_and_group_properties(),
        ]
        select_from_inner = self._get_inner_event_query(skip_entity_filter=True, skip_step_filter=True)
        inner_query = ast.SelectQuery(select=select_inner, select_from=ast.JoinExpr(table=select_from_inner))

        select: list[ast.Expr] = [
            ast.Field(chain=["*"]),
            ast.Alias(alias="steps", expr=self._get_sorting_condition(max_steps, max_steps)),
            *self._get_step_times(max_steps),
            *self._get_matching_events(max_steps),
            *self._get_person_and_group_properties(),
        ]
        select_from = ast.JoinExpr(table=inner_query)
        where = ast.CompareOperation(
            left=ast.Field(chain=["step_0"]), right=ast.Constant(value=1), op=ast.CompareOperationOp.Eq
        )
        return ast.SelectQuery(select=select, select_from=select_from, where=where)

    def _get_partition_cols(self, level_index: int, max_steps: int):
        exprs: list[ast.Expr] = []

        for i in range(0, max_steps):
            exprs.append(ast.Field(chain=[f"step_{i}"]))

            if i < level_index:
                exprs.append(ast.Field(chain=[f"latest_{i}"]))

                for field in self.extra_event_fields_and_properties:
                    exprs.append(ast.Field(chain=[f"{field}_{i}"]))

            else:
                exprs.append(
                    parse_expr(
                        f"min(latest_{i}) over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN {i} PRECEDING AND {i} PRECEDING) as latest_{i}"
                    )
                )

                for field in self.extra_event_fields_and_properties:
                    exprs.append(
                        parse_expr(
                            f'min("{field}_{i}") over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN {i} PRECEDING AND {i} PRECEDING) as "{field}_{i}"'
                        )
                    )

        return exprs
