from abc import ABC
from typing import List, Optional
from posthog.clickhouse.materialized_columns.column import ColumnName
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.utils.entities import is_equal, is_superset
from posthog.models.property.property import PropertyName
from posthog.models.team.team import Team
from posthog.schema import FunnelsQuery, HogQLQueryModifiers


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

    def _get_breakdown_prop(self):
        # TODO: implement
        return ""
