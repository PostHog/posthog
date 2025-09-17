import uuid
from typing import Any, Optional

from rest_framework.exceptions import ValidationError

from posthog.schema import ActionsNode, BreakdownType, DataWarehouseNode, EventsNode

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.insights.funnels.base import FunnelBase
from posthog.hogql_queries.insights.funnels.utils import funnel_window_interval_unit_to_sql
from posthog.queries.util import correct_result_for_sampling


class FunnelUnordered(FunnelBase):
    """
    Unordered Funnel is a funnel where the order of steps doesn't matter.

    ## Query Intuition

    Imagine a funnel with three events: A, B, and C.
    This query splits the problem into two parts:
    1. Given the first event is A, find the furthest everyone went starting from A.
       This finds any B's and C's that happen after A (without ordering them)
    2. Repeat the above, assuming first event to be B, and then C.

    Then, the outer query unions the result of (2) and takes the maximum of these.

    ## Results

    The result format is the same as the basic funnel, i.e. [step, count].
    Here, `step_i` (0 indexed) signifies the number of people that did at least `i+1` steps.

    ## Exclusion Semantics
    For unordered funnels, exclusion is a bit weird. It means, given all ordering of the steps,
    how far can you go without seeing an exclusion event.
    If you see an exclusion event => you're discarded.
    See test_advanced_funnel_multiple_exclusions_between_steps for details.
    """

    def get_query(self):
        max_steps = self.context.max_steps

        for exclusion in self.context.funnelsFilter.exclusions or []:
            if exclusion.funnelFromStep != 0 or exclusion.funnelToStep != max_steps - 1:
                raise ValidationError("Partial Exclusions not allowed in unordered funnels")

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
        )

    def get_step_counts_query(self):
        return self._get_step_counts_query(outer_select=[], inner_select=[])

    def get_step_counts_without_aggregation_query(self):
        max_steps = self.context.max_steps
        union_queries: list[ast.SelectQuery] = []
        entities_to_use = list(self.context.query.series)

        for i in range(max_steps):
            inner_query = ast.SelectQuery(
                select=[
                    ast.Field(chain=["aggregation_target"]),
                    ast.Field(chain=["timestamp"]),
                    *self._get_partition_cols(1, max_steps),
                    *self._get_breakdown_prop_expr(group_remaining=True),
                    *self._get_person_and_group_properties(),
                ],
                select_from=ast.JoinExpr(table=self._get_inner_event_query(entities_to_use, f"events_{i}")),
            )

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

            formatted_query = ast.SelectQuery(
                select=[
                    ast.Field(chain=["*"]),
                    *self.get_sorting_condition(max_steps),
                    *self._get_exclusion_condition(),
                    *self._get_step_times(max_steps),
                    *self._get_person_and_group_properties(),
                ],
                select_from=ast.JoinExpr(table=inner_query),
                where=where,
            )

            #  rotate entities by 1 to get new first event
            entities_to_use.append(entities_to_use.pop(0))
            union_queries.append(formatted_query)

        return ast.SelectSetQuery.create_from_queries(union_queries, "UNION ALL")

    def _get_step_times(self, max_steps: int) -> list[ast.Expr]:
        windowInterval = self.context.funnelWindowInterval
        windowIntervalUnit = funnel_window_interval_unit_to_sql(self.context.funnelWindowIntervalUnit)

        exprs: list[ast.Expr] = []

        conversion_times_elements = []
        for i in range(max_steps):
            conversion_times_elements.append(f"latest_{i}")

        exprs.append(parse_expr(f"arraySort([{','.join(conversion_times_elements)}]) as conversion_times"))

        for i in range(1, max_steps):
            exprs.append(
                parse_expr(
                    f"if(isNotNull(conversion_times[{i+1}]) AND conversion_times[{i+1}] <= toTimeZone(conversion_times[{i}], 'UTC') + INTERVAL {windowInterval} {windowIntervalUnit}, dateDiff('second', conversion_times[{i}], conversion_times[{i+1}]), NULL) as step_{i}_conversion_time"
                )
            )
            # array indices in ClickHouse are 1-based :shrug:

        return exprs

    def get_sorting_condition(self, max_steps: int) -> list[ast.Expr]:
        windowInterval = self.context.funnelWindowInterval
        windowIntervalUnit = funnel_window_interval_unit_to_sql(self.context.funnelWindowIntervalUnit)

        conditions = []

        event_times_elements = []
        for i in range(max_steps):
            event_times_elements.append(f"latest_{i}")

        conditions.append(parse_expr(f"arraySort([{','.join(event_times_elements)}]) as event_times"))
        # replacement of latest_i for whatever query part requires it, just like conversion_times
        basic_conditions: list[str] = []
        for i in range(1, max_steps):
            basic_conditions.append(
                f"if(latest_0 < latest_{i} AND latest_{i} <= toTimeZone(latest_0, 'UTC') + INTERVAL {windowInterval} {windowIntervalUnit}, 1, 0)"
            )

        if basic_conditions:
            conditions.append(ast.Alias(alias="steps", expr=parse_expr(f"arraySum([{','.join(basic_conditions)}, 1])")))
            return conditions
        else:
            return [ast.Alias(alias="steps", expr=ast.Constant(value=1))]

    def _get_exclusion_condition(self) -> list[ast.Expr]:
        funnelsFilter = self.context.funnelsFilter
        windowInterval = self.context.funnelWindowInterval
        windowIntervalUnit = funnel_window_interval_unit_to_sql(self.context.funnelWindowIntervalUnit)

        if not funnelsFilter.exclusions:
            return []

        conditions: list[ast.Expr] = []

        for exclusion_id, exclusion in enumerate(funnelsFilter.exclusions):
            from_time = f"latest_{exclusion.funnelFromStep}"
            to_time = f"event_times[{exclusion.funnelToStep + 1}]"
            exclusion_time = f"exclusion_{exclusion_id}_latest_{exclusion.funnelFromStep}"
            condition = parse_expr(
                f"if( {exclusion_time} > {from_time} AND {exclusion_time} < if(isNull({to_time}), toTimeZone({from_time}, 'UTC') + INTERVAL {windowInterval} {windowIntervalUnit}, {to_time}), 1, 0)"
            )
            conditions.append(condition)

        if conditions:
            return [
                ast.Alias(
                    alias="exclusion",
                    expr=ast.Call(name="arraySum", args=[ast.Array(exprs=conditions)]),
                )
            ]
        else:
            return []

    def _serialize_step(
        self,
        step: ActionsNode | EventsNode | DataWarehouseNode,
        count: int,
        index: int,
        people: Optional[list[uuid.UUID]] = None,
        sampling_factor: Optional[float] = None,
    ) -> dict[str, Any]:
        if isinstance(step, DataWarehouseNode):
            raise NotImplementedError("Data Warehouse queries are not supported in funnels")

        return {
            "action_id": None,
            "name": f"Completed {index+1} step{'s' if index != 0 else ''}",
            "custom_name": None,
            "order": index,
            "people": people if people else [],
            "count": correct_result_for_sampling(count, sampling_factor),
            "type": "events" if isinstance(step, EventsNode) else "actions",
        }
