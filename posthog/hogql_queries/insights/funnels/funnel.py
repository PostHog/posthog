from rest_framework.exceptions import ValidationError

from posthog.schema import BreakdownType

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.insights.funnels.base import FunnelBase


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

        if self.context.breakdown and self.context.breakdownType in [
            BreakdownType.PERSON,
            BreakdownType.EVENT,
            BreakdownType.GROUP,
        ]:
            return self._breakdown_other_subquery()

        breakdown_exprs = self._get_breakdown_prop_expr()

        select: list[ast.Expr] = [
            *self._get_count_columns(max_steps),
            *self._get_step_time_avgs(max_steps),
            *self._get_step_time_median(max_steps),
            *breakdown_exprs,
        ]

        return ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=self.get_step_counts_query()),
            group_by=[ast.Field(chain=["prop"])] if len(breakdown_exprs) > 0 else None,
            order_by=self._order_by() if len(breakdown_exprs) > 0 else None,
        )

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
        if max_steps < 2:
            raise ValidationError("Funnels require at least two steps before calculating.")

        formatted_query = self._build_step_subquery(2, max_steps)
        breakdown_exprs = self._get_breakdown_prop_expr()

        select: list[ast.Expr] = [
            ast.Field(chain=["*"]),
            ast.Alias(alias="steps", expr=self._get_sorting_condition(max_steps, max_steps)),
            *self._get_exclusion_condition(),
            *self._get_step_times(max_steps),
            *self._get_matching_events(max_steps),
            *breakdown_exprs,
            *self._get_person_and_group_properties(),
        ]

        where_exprs = [
            ast.CompareOperation(
                left=ast.Field(chain=["step_0"]), right=ast.Constant(value=1), op=ast.CompareOperationOp.Eq
            ),
            (
                ast.CompareOperation(
                    left=ast.Field(chain=["exclusion"]), right=ast.Constant(value=0), op=ast.CompareOperationOp.Eq
                )
                if self._get_exclusion_condition() != []
                else None
            ),
        ]
        where = ast.And(exprs=[expr for expr in where_exprs if expr is not None])

        return ast.SelectQuery(select=select, select_from=ast.JoinExpr(table=formatted_query), where=where)

    def _build_step_subquery(
        self, level_index: int, max_steps: int, event_names_alias: str = "events"
    ) -> ast.SelectQuery:
        select: list[ast.Expr] = [
            ast.Field(chain=["aggregation_target"]),
            ast.Field(chain=["timestamp"]),
        ]

        if level_index >= max_steps:
            select = [
                *select,
                *self._get_partition_cols(1, max_steps),
                *self._get_breakdown_prop_expr(group_remaining=True),
                *self._get_person_and_group_properties(),
            ]

            event_query = self._get_inner_event_query(entity_name=event_names_alias)

            return ast.SelectQuery(select=select, select_from=ast.JoinExpr(table=event_query))
        else:
            outer_select = [
                *select,
                *self._get_partition_cols(level_index, max_steps),
                *self._get_breakdown_prop_expr(),
                *self._get_person_and_group_properties(),
            ]
            inner_select = [
                *select,
                *self._get_comparison_cols(level_index, max_steps),
                *self._get_breakdown_prop_expr(),
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

    def _get_comparison_cols(self, level_index: int, max_steps: int) -> list[ast.Expr]:
        """
        level_index: The current smallest comparison step. Everything before
        level index is already at the minimum ordered timestamps.
        """
        exprs: list[ast.Expr] = []
        funnelsFilter = self.context.funnelsFilter
        exclusions = funnelsFilter.exclusions

        for i in range(0, max_steps):
            exprs.append(ast.Field(chain=[f"step_{i}"]))

            if i < level_index:
                exprs.append(ast.Field(chain=[f"latest_{i}"]))

                for field in self.extra_event_fields_and_properties:
                    exprs.append(ast.Field(chain=[f"{field}_{i}"]))

                for exclusion_id, exclusion in enumerate(exclusions or []):
                    if exclusion.funnelFromStep + 1 == i:
                        exprs.append(ast.Field(chain=[f"exclusion_{exclusion_id}_latest_{exclusion.funnelFromStep}"]))

            else:
                comparison = self._get_comparison_at_step(i, level_index)
                exprs.append(
                    parse_expr(
                        f"if({{comparison}}, NULL, latest_{i}) as latest_{i}", placeholders={"comparison": comparison}
                    )
                )

                for field in self.extra_event_fields_and_properties:
                    exprs.append(
                        parse_expr(
                            f'if({{comparison}}, NULL, "{field}_{i}") as "{field}_{i}"',
                            placeholders={"comparison": comparison},
                        )
                    )

                for exclusion_id, exclusion in enumerate(exclusions or []):
                    if exclusion.funnelFromStep + 1 == i:
                        exclusion_identifier = f"exclusion_{exclusion_id}_latest_{exclusion.funnelFromStep}"
                        exprs.append(
                            parse_expr(
                                f"if({exclusion_identifier} < latest_{exclusion.funnelFromStep}, NULL, {exclusion_identifier}) as {exclusion_identifier}"
                            )
                        )

        return exprs

    def _get_comparison_at_step(self, index: int, level_index: int) -> ast.Or:
        exprs: list[ast.Expr] = []

        for i in range(level_index, index + 1):
            exprs.append(parse_expr(f"latest_{i} < latest_{level_index - 1}"))

        return ast.Or(exprs=exprs)
