from abc import ABC
from typing import List, Optional, Tuple
from posthog.clickhouse.materialized_columns.column import ColumnName
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.utils.entities import is_equal, is_superset
from posthog.hogql_queries.insights.utils.funnels_filter import funnel_window_interval_unit_to_sql
from posthog.models.property.property import PropertyName
from posthog.models.team.team import Team
from posthog.schema import BreakdownFilter, FunnelsQuery, HogQLQueryModifiers


class FunnelBase(ABC):
    context: FunnelQueryContext

    _extra_event_fields: List[ColumnName]
    _extra_event_properties: List[PropertyName]

    def __init__(
        self,
        query: FunnelsQuery,
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        self.context = FunnelQueryContext(
            query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context
        )

        self._extra_event_fields: List[ColumnName] = []
        self._extra_event_properties: List[PropertyName] = []
        if False:  # self._filter.include_recordings: TODO: implement with actors query
            self._extra_event_fields = ["uuid"]
            self._extra_event_properties = ["$session_id", "$window_id"]

    @property
    def extra_event_fields_and_properties(self):
        return self._extra_event_fields + self._extra_event_properties

    def _get_timestamp_selects(self) -> Tuple[List[ast.Expr], List[ast.Expr]]:
        """
        Returns timestamp selectors for the target step and optionally the preceding step.
        In the former case, always returns the timestamp for the first and last step as well.
        """
        # target_step = self._filter.funnel_step # TODO: implement with actors
        # final_step = self.context.max_steps - 1
        # first_step = 0

        # if not target_step:
        #     return "", ""

        # if target_step < 0:
        #     # the first valid dropoff argument for funnel_step is -2
        #     # -2 refers to persons who performed the first step but never made it to the second
        #     if target_step == -1:
        #         raise ValueError("To request dropoff of initial step use -2")

        #     target_step = abs(target_step) - 2
        # else:
        #     target_step -= 1

        # if self._include_preceding_timestamp:
        #     if target_step == 0:
        #         raise ValueError("Cannot request preceding step timestamp if target funnel step is the first step")

        #     return (
        #         f", latest_{target_step}, latest_{target_step - 1}",
        #         f", argMax(latest_{target_step}, steps) as max_timestamp, argMax(latest_{target_step - 1}, steps) as min_timestamp",
        #     )
        # elif self._include_timestamp:
        #     return (
        #         f", latest_{target_step}, latest_{final_step}, latest_{first_step}",
        #         f", argMax(latest_{target_step}, steps) as timestamp, argMax(latest_{final_step}, steps) as final_timestamp, argMax(latest_{first_step}, steps) as first_timestamp",
        #     )
        # else:
        #     return "", ""
        return [], []

    def _get_partition_cols(self, level_index: int, max_steps: int) -> List[ast.Expr]:
        # funnelsFilter = self.context.query.funnelsFilter or FunnelsFilter()
        # exclusions = funnelsFilter.exclusions
        series = self.context.query.series

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
                duplicate_event = 0

                if i > 0 and (is_equal(series[i], series[i - 1]) or is_superset(series[i], series[i - 1])):
                    duplicate_event = 1

                exprs.append(
                    parse_expr(
                        f"min(latest_{i}) over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND {duplicate_event} PRECEDING) latest_{i}"
                    )
                )

                # for field in self.extra_event_fields_and_properties:
                #     cols.append(
                #         f'last_value("{field}_{i}") over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND {duplicate_event} PRECEDING) "{field}_{i}"'
                #     )

                # for exclusion_id, exclusion in enumerate(self._filter.exclusions):
                #     # exclusion starting at step i follows semantics of step i+1 in the query (since we're looking for exclusions after step i)
                #     if cast(int, exclusion.funnel_from_step) + 1 == i:
                #         cols.append(
                #             f"min(exclusion_{exclusion_id}_latest_{exclusion.funnel_from_step}) over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) exclusion_{exclusion_id}_latest_{exclusion.funnel_from_step}"
                #         )

        return exprs

    def _get_breakdown_prop(self, group_remaining=False) -> List[ast.Expr]:
        # if self._filter.breakdown:
        #     other_aggregation = "['Other']" if self._query_has_array_breakdown() else "'Other'"
        #     if group_remaining and self._filter.breakdown_type in [
        #         "person",
        #         "event",
        #         "group",
        #     ]:
        #         return f", if(has(%(breakdown_values)s, prop), prop, {other_aggregation}) as prop"
        #     else:
        #         # Cohorts don't have "Other" aggregation
        #         return ", prop"
        # else:
        #     return ""
        return []

    def _query_has_array_breakdown(self) -> bool:
        breakdown, breakdown_type = self.context.breakdownFilter.breakdown, self.context.breakdownFilter.breakdown_type
        return not isinstance(breakdown, str) and breakdown_type != "cohort"

    def _get_sorting_condition(self, curr_index: int, max_steps: int) -> ast.Expr:
        series = self.context.query.series
        funnelWindowInterval = self.context.funnelsFilter.funnelWindowInterval
        funnelWindowIntervalUnit = funnel_window_interval_unit_to_sql(
            self.context.funnelsFilter.funnelWindowIntervalUnit
        )

        if curr_index == 1:
            return ast.Constant(value=1)

        conditions: List[ast.Expr] = []

        for i in range(1, curr_index):
            duplicate_event = is_equal(series[i], series[i - 1]) or is_superset(series[i], series[i - 1])

            conditions.append(parse_expr(f"latest_{i - 1} {'<' if duplicate_event else '<='} latest_{i}"))
            conditions.append(
                parse_expr(f"latest_{i} <= latest_0 + INTERVAL {funnelWindowInterval} {funnelWindowIntervalUnit}")
            )

        return ast.Call(
            name="if",
            args=[
                ast.And(exprs=conditions),
                ast.Constant(value=curr_index),
                self._get_sorting_condition(curr_index - 1, max_steps),
            ],
        )

    def _get_person_and_group_properties(self) -> List[ast.Expr]:
        exprs: List[ast.Expr] = []

        # for prop in self._include_properties:
        #     exprs.append(f"any({prop}) as {prop}" if aggregate else prop)

        return exprs

