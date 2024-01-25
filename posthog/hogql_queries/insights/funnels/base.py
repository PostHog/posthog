from abc import ABC
from typing import List, Tuple
from posthog.clickhouse.materialized_columns.column import ColumnName
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql_queries.insights.funnels.funnel_event_query import FunnelEventQuery
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.utils.entities import is_equal, is_superset
from posthog.hogql_queries.insights.utils.funnels_filter import funnel_window_interval_unit_to_sql
from posthog.models.property.property import PropertyName
from posthog.types import EntityNode


class FunnelBase(ABC):
    context: FunnelQueryContext

    _extra_event_fields: List[ColumnName]
    _extra_event_properties: List[PropertyName]

    def __init__(
        self,
        context: FunnelQueryContext,
    ):
        self.context = context

        self._extra_event_fields: List[ColumnName] = []
        self._extra_event_properties: List[PropertyName] = []

        if False:  # self._filter.include_recordings: TODO: implement with actors query
            self._extra_event_fields = ["uuid"]
            self._extra_event_properties = ["$session_id", "$window_id"]

    @property
    def extra_event_fields_and_properties(self):
        return self._extra_event_fields + self._extra_event_properties

    def _get_inner_event_query(
        self,
        entities: List[EntityNode] | None = None,
        entity_name="events",
        skip_entity_filter=False,
        skip_step_filter=False,
    ) -> ast.SelectQuery:
        entities_to_use = entities or self.context.query.series

        # extra_fields = []

        # for prop in self._include_properties:
        #     extra_fields.append(prop)

        funnel_events_query = FunnelEventQuery(context=self.context).to_query()
        # funnel_events_query, params = FunnelEventQuery(
        #     extra_fields=[*self._extra_event_fields, *extra_fields],
        #     extra_event_properties=self._extra_event_properties,
        # ).get_query(entities_to_use, entity_name, skip_entity_filter=skip_entity_filter)

        # if skip_step_filter:
        #     steps_conditions = "1=1"
        # else:
        #     steps_conditions = self._get_steps_conditions(length=len(entities_to_use))

        all_step_cols: List[ast.Expr] = []
        for index, entity in enumerate(entities_to_use):
            step_cols = self._get_step_col(entity, index, entity_name)
            all_step_cols.extend(step_cols)

        # for exclusion_id, entity in enumerate(self._filter.exclusions):
        #     step_cols = self._get_step_col(
        #         entity,
        #         entity.funnel_from_step,
        #         entity_name,
        #         f"exclusion_{exclusion_id}_",
        #     )
        #     # every exclusion entity has the form: exclusion_<id>_step_i & timestamp exclusion_<id>_latest_i
        #     # where i is the starting step for exclusion on that entity
        #     all_step_cols.extend(step_cols)

        # breakdown_select_prop, breakdown_select_prop_params = self._get_breakdown_select_prop()

        # if breakdown_select_prop:
        #     all_step_cols.append(breakdown_select_prop)

        # extra_join = ""

        # if self._filter.breakdown:
        #     if self._filter.breakdown_type == "cohort":
        #         extra_join = self._get_cohort_breakdown_join()
        #     else:
        #         values = self._get_breakdown_conditions()
        #         self.params.update({"breakdown_values": values})

        funnel_events_query.select = [*funnel_events_query.select, *all_step_cols]

        # funnel_events_query = funnel_events_query.format(
        #     # extra_join=extra_join,
        #     # step_filter="AND ({})".format(steps_conditions),
        # )

        # if self._filter.breakdown and self._filter.breakdown_attribution_type != BreakdownAttributionType.ALL_EVENTS:
        #     # ALL_EVENTS attribution is the old default, which doesn't need the subquery
        #     return self._add_breakdown_attribution_subquery(funnel_events_query)

        return funnel_events_query

    # def _get_steps_conditions(self, length: int) -> str:
    #     step_conditions: List[str] = []

    #     for index in range(length):
    #         step_conditions.append(f"step_{index} = 1")

    #     for exclusion_id, entity in enumerate(self._filter.exclusions):
    #         step_conditions.append(f"exclusion_{exclusion_id}_step_{entity.funnel_from_step} = 1")

    #     return " OR ".join(step_conditions)

    def _get_step_col(self, entity: EntityNode, index: int, entity_name: str, step_prefix: str = "") -> List[ast.Expr]:
        # step prefix is used to distinguish actual steps, and exclusion steps
        # without the prefix, we get the same parameter binding for both, which borks things up
        step_cols: List[ast.Expr] = []
        condition = self._build_step_query(entity, index, entity_name, step_prefix)
        step_cols.append(
            parse_expr(f"if({{condition}}, 1, 0) as {step_prefix}step_{index}", placeholders={"condition": condition})
        )
        step_cols.append(
            parse_expr(f"if({step_prefix}step_{index} = 1, timestamp, null) as {step_prefix}latest_{index}")
        )

        # for field in self.extra_event_fields_and_properties:
        #     step_cols.append(f'if({step_prefix}step_{index} = 1, "{field}", null) as "{step_prefix}{field}_{index}"')

        return step_cols

    def _build_step_query(self, entity: EntityNode, index: int, entity_name: str, step_prefix: str) -> ast.Expr:
        # filters = self._build_filters(entity, index, entity_name)
        # if isinstance(entity, ActionsNode):
        #     action = Action.objects.get(pk=int(entity.id), team=self.context.team)
        #     for action_step_event in action.get_step_events():
        #         if entity_name not in self.params[entity_name]:
        #             self.params[entity_name].append(action_step_event)

        #     action_query, action_params = format_action_filter(
        #         team_id=self._team.pk,
        #         action=action,
        #         prepend=f"{entity_name}_{step_prefix}step_{index}",
        #         person_properties_mode=get_person_properties_mode(self._team),
        #         person_id_joined_alias="person_id",
        #         hogql_context=self._filter.hogql_context,
        #     )
        #     if action_query == "":
        #         return ""

        #     self.params.update(action_params)
        #     expr = "{actions_query} {filters}".format(actions_query=action_query, filters=filters)
        # elif entity.id is None:
        #     # all events
        #     # expr = f"1 = 1 {filters}"
        #     expr = ast.Constant(value=True)
        # else:
        #     if entity_name not in self.params:
        #         self.params[entity_name] = []
        #     if entity.id not in self.params[entity_name]:
        #         self.params[entity_name].append(entity.id)
        #     event_param_key = f"{entity_name}_{step_prefix}event_{index}"
        #     self.params[event_param_key] = entity.id
        #     expr = f"event = %({event_param_key})s {filters}"
        # return expr
        return ast.Constant(value=True)

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
        return [], []

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
                    # TODO: fix breakdown
                    # parse_expr(
                    #     f"min(latest_{i}) over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND {duplicate_event} PRECEDING) latest_{i}"
                    # )
                    parse_expr(
                        f"min(latest_{i}) over (PARTITION by aggregation_target ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND {duplicate_event} PRECEDING) latest_{i}"
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
        windowInterval = self.context.funnelWindowInterval
        windowIntervalUnit = funnel_window_interval_unit_to_sql(self.context.funnelWindowIntervalUnit)

        if curr_index == 1:
            return ast.Constant(value=1)

        conditions: List[ast.Expr] = []

        for i in range(1, curr_index):
            duplicate_event = is_equal(series[i], series[i - 1]) or is_superset(series[i], series[i - 1])

            conditions.append(parse_expr(f"latest_{i - 1} {'<' if duplicate_event else '<='} latest_{i}"))
            conditions.append(parse_expr(f"latest_{i} <= latest_0 + INTERVAL {windowInterval} {windowIntervalUnit}"))

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
