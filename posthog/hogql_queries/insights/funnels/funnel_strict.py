from typing import List

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql_queries.insights.funnels.base import FunnelBase


class FunnelStrict(FunnelBase):
    def get_query(self):
        max_steps = self.context.max_steps

        # breakdown_exprs = self._get_breakdown_prop_expr()

        select: List[ast.Expr] = [
            *self._get_count_columns(max_steps),
            *self._get_step_time_avgs(max_steps),
            *self._get_step_time_median(max_steps),
            # *breakdown_exprs,
        ]

        return ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=self.get_step_counts_query()),
            # group_by=[ast.Field(chain=["prop"])] if len(breakdown_exprs) > 0 else None,
        )

    def get_step_counts_query(self):
        max_steps = self.context.max_steps
        # breakdown_exprs = self._get_breakdown_prop_expr()
        inner_timestamps, outer_timestamps = self._get_timestamp_selects()
        person_and_group_properties = self._get_person_and_group_properties()

        group_by_columns: List[ast.Expr] = [
            ast.Field(chain=["aggregation_target"]),
            ast.Field(chain=["steps"]),
            # *breakdown_exprs,
        ]

        outer_select: List[ast.Expr] = [
            *group_by_columns,
            *self._get_step_time_avgs(max_steps, inner_query=True),
            *self._get_step_time_median(max_steps, inner_query=True),
            *self._get_matching_event_arrays(max_steps),
            # *breakdown_exprs,
            *outer_timestamps,
            *person_and_group_properties,
        ]

        max_steps_expr = parse_expr(
            f"max(steps) over (PARTITION BY aggregation_target {self._get_breakdown_prop()}) as max_steps"
        )

        inner_select: List[ast.Expr] = [
            *group_by_columns,
            max_steps_expr,
            *self._get_step_time_names(max_steps),
            *self._get_matching_events(max_steps),
            # *breakdown_exprs,
            *inner_timestamps,
            *person_and_group_properties,
        ]

        return ast.SelectQuery(
            select=outer_select,
            select_from=ast.JoinExpr(
                table=ast.SelectQuery(
                    select=inner_select,
                    select_from=ast.JoinExpr(table=self.get_step_counts_without_aggregation_query()),
                )
            ),
            group_by=group_by_columns,
            having=ast.CompareOperation(
                left=ast.Field(chain=["steps"]), right=ast.Field(chain=["max_steps"]), op=ast.CompareOperationOp.Eq
            ),
        )

    def get_step_counts_without_aggregation_query(self):
        max_steps = self.context.max_steps

        select_inner: List[ast.Expr] = [
            ast.Field(chain=["aggregation_target"]),
            ast.Field(chain=["timestamp"]),
            *self._get_partition_cols(1, max_steps),
            # *self._get_breakdown_prop_expr(group_remaining=True),
            *self._get_person_and_group_properties(),
        ]
        select_from_inner = self._get_inner_event_query(skip_entity_filter=True, skip_step_filter=True)
        inner_query = ast.SelectQuery(select=select_inner, select_from=ast.JoinExpr(table=select_from_inner))

        select: List[ast.Expr] = [
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
        exprs: List[ast.Expr] = []

        for i in range(0, max_steps):
            exprs.append(ast.Field(chain=[f"step_{i}"]))

            if i < level_index:
                exprs.append(ast.Field(chain=[f"latest_{i}"]))

                # for field in self.extra_event_fields_and_properties:
                #     exprs.append(ast.Field(chain=[f'"{field}_{i}"']))

            else:
                exprs.append(
                    parse_expr(
                        f"min(latest_{i}) over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN {i} PRECEDING AND {i} PRECEDING) latest_{i}"
                    )
                )

                # for field in self.extra_event_fields_and_properties:
                #     exprs.append(
                #         parse_expr(
                #             f'min("{field}_{i}") over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN {i} PRECEDING AND {i} PRECEDING) "{field}_{i}"'
                #         )
                #     )

        return exprs
