from typing import List

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql_queries.insights.funnels.base import FunnelBase

from rest_framework.exceptions import ValidationError


class Funnel(FunnelBase):
    """
    A basic ordered funnel.

    ## Query Intuition
    We start with all events of interest (coming from the `FunnelEventQuery`). The query runs in different levels: at each
    level, we first get the minimum timestamp of every event following the previous event. Then, we trickle up the levels, till we get to the top level,
    which implies all events are sorted in increasing order.
    Each level is a subquery.

    ## Exclusion Intuition
    Event exclusion between steps means that if this specific event happened between two funnel steps, we disqualify the user, not showing them in the results.
    To include event exclusions inside the funnel, the critical insight is that the exclusion is just like a parallel step to the funnel step that happens after
    the exclusion start step.
    For example, if we have a funnel with steps [1, 2, 3, 4] and we want to exclude events between step 2 and step 4, then the exclusion step semantics are just
    like step 3 semantics. We want to find this event after step 2.
    Since it's a parallel step, we don't need to add an extra level, we can reuse the existing levels.
    See `get_comparison_cols` and `_get_partition_cols` for how this works.

    Exclusion doesn't support duplicates like: steps [event 1, event 2], and excluding event 1 between steps 1 and 2.

    """

    def get_query(self):
        max_steps = self.context.max_steps

        breakdown_exprs = self._get_breakdown_prop()

        select: List[ast.Expr] = [
            *self._get_count_columns(max_steps),
            *self._get_step_time_avgs(max_steps),
            *self._get_step_time_median(max_steps),
            *breakdown_exprs,
        ]

        return ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=self.get_step_counts_query()),
            group_by=[ast.Field(chain=["prop"])] if len(breakdown_exprs) > 0 else None,
        )

    def get_step_counts_query(self):
        max_steps = self.context.max_steps
        breakdown_exprs = self._get_breakdown_prop()
        inner_timestamps, outer_timestamps = self._get_timestamp_selects()
        person_and_group_properties = self._get_person_and_group_properties()

        group_by_columns: List[ast.Expr] = [
            ast.Field(chain=["aggregation_target"]),
            ast.Field(chain=["steps"]),
            *breakdown_exprs,
        ]

        outer_select: List[ast.Expr] = [
            *group_by_columns,
            *self._get_step_time_avgs(max_steps, inner_query=True),
            *self._get_step_time_median(max_steps, inner_query=True),
            *self._get_matching_event_arrays(max_steps),
            *breakdown_exprs,
            *outer_timestamps,
            *person_and_group_properties,
        ]

        # TODO: max(steps) over (PARTITION BY aggregation_target {breakdown_clause}) as max_steps
        max_steps_expr = parse_expr("max(steps) over (PARTITION BY aggregation_target) as max_steps")
        max_steps_expr.expr.over_expr.partition_by = [
            *max_steps_expr.expr.over_expr.partition_by,
            *breakdown_exprs,
        ]

        inner_select: List[ast.Expr] = [
            *group_by_columns,
            max_steps_expr,
            *self._get_step_time_names(max_steps),
            *self._get_matching_events(max_steps),
            *breakdown_exprs,
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
        if max_steps < 2:
            raise ValidationError("Funnels require at least two steps before calculating.")

        formatted_query = self._build_step_subquery(2, max_steps)
        breakdown_exprs = self._get_breakdown_prop()

        # exclusion_clause = self._get_exclusion_condition()

        select: List[ast.Expr] = [
            ast.Field(chain=["*"]),
            ast.Alias(alias="steps", expr=self._get_sorting_condition(max_steps, max_steps)),
            # {exclusion_clause}
            *self._get_step_times(max_steps),
            *self._get_matching_events(max_steps),
            *breakdown_exprs,
            *self._get_person_and_group_properties(),
        ]

        # return f"""
        # SELECT
        #     *,
        #     {self._get_sorting_condition(max_steps, max_steps)} AS steps
        #     {exclusion_clause}
        #     {self._get_step_times(max_steps)}{self._get_matching_events(max_steps)}
        #     {breakdown_query}
        #     {self._get_person_and_group_properties()}
        # FROM (
        #     {formatted_query}
        # ) WHERE step_0 = 1
        # {'AND exclusion = 0' if exclusion_clause else ''}
        # """

        where: ast.Expr = ast.And(
            exprs=[
                ast.CompareOperation(
                    left=ast.Field(chain=["step_0"]), right=ast.Constant(value=1), op=ast.CompareOperationOp.Eq
                )
            ]
        )

        return ast.SelectQuery(select=select, select_from=ast.JoinExpr(table=formatted_query), where=where)

    def _build_step_subquery(
        self, level_index: int, max_steps: int, event_names_alias: str = "events"
    ) -> ast.SelectQuery:
        select: List[ast.Expr] = [
            ast.Field(chain=["aggregation_target"]),
            ast.Field(chain=["timestamp"]),
        ]

        if level_index >= max_steps:
            select = [
                *select,
                *self._get_partition_cols(1, max_steps),
                *self._get_breakdown_prop(group_remaining=True),
                *self._get_person_and_group_properties(),
            ]

            event_query = self._get_inner_event_query(entity_name=event_names_alias)

            return ast.SelectQuery(select=select, select_from=ast.JoinExpr(table=event_query))
        else:
            outer_select = [
                *select,
                *self._get_partition_cols(level_index, max_steps),
                *self._get_breakdown_prop(),
                *self._get_person_and_group_properties(),
            ]
            inner_select = [
                *select,
                *self._get_comparison_cols(level_index, max_steps),
                *self._get_breakdown_prop(),
                *self._get_person_and_group_properties(),
            ]

            return ast.SelectQuery(
                select=outer_select,
                select_from=ast.JoinExpr(
                    table=ast.SelectQuery(
                        select=inner_select,
                        select_from=ast.JoinExpr(table=self._build_step_subquery(level_index + 1, max_steps)),
                    )
                ),
            )

    def _get_comparison_cols(self, level_index: int, max_steps: int) -> List[ast.Expr]:
        """
        level_index: The current smallest comparison step. Everything before
        level index is already at the minimum ordered timestamps.
        """
        exprs: List[ast.Expr] = []

        for i in range(0, max_steps):
            exprs.append(ast.Field(chain=[f"step_{i}"]))

            if i < level_index:
                exprs.append(ast.Field(chain=[f"latest_{i}"]))

                # for field in self.extra_event_fields_and_properties:
                #     exprs.append(ast.Field(chain=[f'"{field}_{i}"']))

                # for exclusion_id, exclusion in enumerate(exclusions or []):
                #     if cast(int, exclusion.funnelFromStep) + 1 == i:
                #         exprs.append(ast.Field(chain=[f"exclusion_{exclusion_id}_latest_{exclusion.funnelFromStep}"]))

            else:
                comparison = self._get_comparison_at_step(i, level_index)
                exprs.append(
                    parse_expr(
                        f"if({{comparison}}, NULL, latest_{i}) as latest_{i}", placeholders={"comparison": comparison}
                    )
                )

                # for field in self.extra_event_fields_and_properties:
                #     exprs.append(f'if({comparison}, NULL, "{field}_{i}") as "{field}_{i}"')

                # for exclusion_id, exclusion in enumerate(self._filter.exclusions):
                #     if cast(int, exclusion.funnel_from_step) + 1 == i:
                #         exclusion_identifier = f"exclusion_{exclusion_id}_latest_{exclusion.funnel_from_step}"
                #         exprs.append(
                #             f"if({exclusion_identifier} < latest_{exclusion.funnel_from_step}, NULL, {exclusion_identifier}) as {exclusion_identifier}"
                #         )

        return exprs

    def _get_comparison_at_step(self, index: int, level_index: int) -> ast.Or:
        exprs: List[ast.Expr] = []

        for i in range(level_index, index + 1):
            exprs.append(parse_expr(f"latest_{i} < latest_{level_index - 1}"))

        return ast.Or(exprs=exprs)
