from abc import ABC
from typing import Any, Dict, List, Optional, Tuple, cast
import uuid
from posthog.clickhouse.materialized_columns.column import ColumnName
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.hogql_queries.insights.funnels.funnel_event_query import FunnelEventQuery
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.utils.entities import is_equal, is_superset
from posthog.hogql_queries.insights.utils.funnels_filter import funnel_window_interval_unit_to_sql
from posthog.models.action.action import Action
from posthog.models.property.property import PropertyName
from posthog.queries.util import correct_result_for_sampling
from posthog.schema import ActionsNode, EventsNode, FunnelExclusionActionsNode
from posthog.types import EntityNode, ExclusionEntityNode


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

        # TODO: implement with actors query
        # if self._filter.include_recordings:
        #     self._extra_event_fields = ["uuid"]
        #     self._extra_event_properties = ["$session_id", "$window_id"]

    def get_query(self) -> ast.SelectQuery:
        raise NotImplementedError()

    def get_step_counts_query(self) -> str:
        raise NotImplementedError()

    def get_step_counts_without_aggregation_query(self) -> str:
        raise NotImplementedError()

    def _format_results(self, results) -> List[Dict[str, Any]]:
        breakdownFilter = self.context.breakdownFilter

        if not results or len(results) == 0:
            return []

        if breakdownFilter.breakdown:
            return [self._format_single_funnel(res, with_breakdown=True) for res in results]
        else:
            return self._format_single_funnel(results[0])

    def _format_single_funnel(self, results, with_breakdown=False):
        max_steps = self.context.max_steps

        # Format of this is [step order, person count (that reached that step), array of person uuids]
        steps = []
        total_people = 0

        # breakdown_value = results[-1]
        # cache_invalidation_key = generate_short_id()

        for index, step in enumerate(reversed(self.context.query.series)):
            step_index = max_steps - 1 - index

            if results and len(results) > 0:
                total_people += results[step_index]

            serialized_result = self._serialize_step(
                step, total_people, step_index, [], self.context.query.samplingFactor
            )  # persons not needed on initial return

            if step_index > 0:
                serialized_result.update(
                    {
                        "average_conversion_time": results[step_index + max_steps - 1],
                        "median_conversion_time": results[step_index + max_steps * 2 - 2],
                    }
                )
            else:
                serialized_result.update({"average_conversion_time": None, "median_conversion_time": None})

            # # Construct converted and dropped people URLs
            # funnel_step = step.index + 1
            # converted_people_filter = self._filter.shallow_clone({"funnel_step": funnel_step})
            # dropped_people_filter = self._filter.shallow_clone({"funnel_step": -funnel_step})

            # if with_breakdown:
            #     # breakdown will return a display ready value
            #     # breakdown_value will return the underlying id if different from display ready value (ex: cohort id)
            #     serialized_result.update(
            #         {
            #             "breakdown": get_breakdown_cohort_name(breakdown_value)
            #             if self._filter.breakdown_type == "cohort"
            #             else breakdown_value,
            #             "breakdown_value": breakdown_value,
            #         }
            #     )
            #     # important to not try and modify this value any how - as these
            #     # are keys for fetching persons

            #     # Add in the breakdown to people urls as well
            #     converted_people_filter = converted_people_filter.shallow_clone(
            #         {"funnel_step_breakdown": breakdown_value}
            #     )
            #     dropped_people_filter = dropped_people_filter.shallow_clone({"funnel_step_breakdown": breakdown_value})

            # serialized_result.update(
            #     {
            #         "converted_people_url": f"{self._base_uri}api/person/funnel/?{urllib.parse.urlencode(converted_people_filter.to_params())}&cache_invalidation_key={cache_invalidation_key}",
            #         "dropped_people_url": (
            #             f"{self._base_uri}api/person/funnel/?{urllib.parse.urlencode(dropped_people_filter.to_params())}&cache_invalidation_key={cache_invalidation_key}"
            #             # NOTE: If we are looking at the first step, there is no drop off,
            #             # everyone converted, otherwise they would not have been
            #             # included in the funnel.
            #             if step.index > 0
            #             else None
            #         ),
            #     }
            # )

            steps.append(serialized_result)

        return steps[::-1]  # reverse

    def _serialize_step(
        self,
        step: ActionsNode | EventsNode,
        count: int,
        index: int,
        people: Optional[List[uuid.UUID]] = None,
        sampling_factor: Optional[float] = None,
    ) -> Dict[str, Any]:
        if isinstance(step, EventsNode):
            name = step.event
        else:
            action = Action.objects.get(pk=step.id)
            name = action.name

        return {
            "action_id": step.event if isinstance(step, EventsNode) else str(step.id),
            "name": name,
            "custom_name": step.custom_name,
            "order": index,
            "people": people if people else [],
            "count": correct_result_for_sampling(count, sampling_factor),
            "type": "events" if isinstance(step, EventsNode) else "actions",
        }

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
        query, funnelsFilter = self.context.query, self.context.funnelsFilter
        entities_to_use = entities or query.series

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

        for exclusion_id, entity in enumerate(funnelsFilter.exclusions or []):
            step_cols = self._get_step_col(entity, entity.funnelFromStep, entity_name, f"exclusion_{exclusion_id}_")
            # every exclusion entity has the form: exclusion_<id>_step_i & timestamp exclusion_<id>_latest_i
            # where i is the starting step for exclusion on that entity
            all_step_cols.extend(step_cols)

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

    def _get_step_col(
        self,
        entity: EntityNode | ExclusionEntityNode,
        index: int,
        entity_name: str,
        step_prefix: str = "",
    ) -> List[ast.Expr]:
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

    def _build_step_query(
        self,
        entity: EntityNode | ExclusionEntityNode,
        index: int,
        entity_name: str,
        step_prefix: str,
    ) -> ast.Expr:
        if isinstance(entity, ActionsNode) or isinstance(entity, FunnelExclusionActionsNode):
            # action
            action = Action.objects.get(pk=int(entity.id), team=self.context.team)
            event_expr = action_to_expr(action)
        elif entity.event is None:
            # all events
            event_expr = ast.Constant(value=True)
        else:
            # event
            event_expr = parse_expr(f"event = '{entity.event}'")

        if entity.properties is not None and entity.properties != []:
            # add property filters
            filter_expr = property_to_expr(entity.properties, self.context.team)
            return ast.And(exprs=[event_expr, filter_expr])
        else:
            return event_expr

    def _get_count_columns(self, max_steps: int) -> List[ast.Expr]:
        exprs: List[ast.Expr] = []

        for i in range(max_steps):
            exprs.append(parse_expr(f"countIf(steps = {i + 1}) step_{i + 1}"))

        return exprs

    def _get_step_time_names(self, max_steps: int) -> List[ast.Expr]:
        exprs: List[ast.Expr] = []

        for i in range(1, max_steps):
            exprs.append(parse_expr(f"step_{i}_conversion_time"))

        return exprs

    # def _get_final_matching_event(self, max_steps: int):
    #     statement = None
    #     for i in range(max_steps - 1, -1, -1):
    #         if i == max_steps - 1:
    #             statement = f"if(isNull(latest_{i}),step_{i-1}_matching_event,step_{i}_matching_event)"
    #         elif i == 0:
    #             statement = f"if(isNull(latest_0),(null,null,null,null),{statement})"
    #         else:
    #             statement = f"if(isNull(latest_{i}),step_{i-1}_matching_event,{statement})"
    #     return f",{statement} as final_matching_event" if statement else ""

    def _get_matching_events(self, max_steps: int) -> List[ast.Expr]:
        # if self._filter.include_recordings:
        #     events = []
        #     for i in range(0, max_steps):
        #         event_fields = ["latest"] + self.extra_event_fields_and_properties
        #         event_fields_with_step = ", ".join([f'"{field}_{i}"' for field in event_fields])
        #         event_clause = f"({event_fields_with_step}) as step_{i}_matching_event"
        #         events.append(event_clause)
        #     matching_event_select_statements = "," + ", ".join(events)

        #     final_matching_event_statement = self._get_final_matching_event(max_steps)

        #     return matching_event_select_statements + final_matching_event_statement

        return []

    def _get_matching_event_arrays(self, max_steps: int) -> List[ast.Expr]:
        # select_clause = ""
        # if self._filter.include_recordings:
        #     for i in range(0, max_steps):
        #         select_clause += f", groupArray(10)(step_{i}_matching_event) as step_{i}_matching_events"
        #     select_clause += f", groupArray(10)(final_matching_event) as final_matching_events"
        # return select_clause
        return []

    def _get_step_time_avgs(self, max_steps: int, inner_query: bool = False) -> List[ast.Expr]:
        exprs: List[ast.Expr] = []

        for i in range(1, max_steps):
            exprs.append(
                parse_expr(f"avg(step_{i}_conversion_time) step_{i}_average_conversion_time_inner")
                if inner_query
                else parse_expr(f"avg(step_{i}_average_conversion_time_inner) step_{i}_average_conversion_time")
            )

        return exprs

    def _get_step_time_median(self, max_steps: int, inner_query: bool = False) -> List[ast.Expr]:
        exprs: List[ast.Expr] = []

        for i in range(1, max_steps):
            exprs.append(
                parse_expr(f"median(step_{i}_conversion_time) step_{i}_median_conversion_time_inner")
                if inner_query
                else parse_expr(f"median(step_{i}_median_conversion_time_inner) step_{i}_median_conversion_time")
            )

        return exprs

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

    def _get_step_times(self, max_steps: int) -> List[ast.Expr]:
        windowInterval = self.context.funnelWindowInterval
        windowIntervalUnit = funnel_window_interval_unit_to_sql(self.context.funnelWindowIntervalUnit)

        exprs: List[ast.Expr] = []

        for i in range(1, max_steps):
            exprs.append(
                parse_expr(
                    f"if(isNotNull(latest_{i}) AND latest_{i} <= latest_{i-1} + INTERVAL {windowInterval} {windowIntervalUnit}, dateDiff('second', latest_{i - 1}, latest_{i}), NULL) step_{i}_conversion_time"
                ),
            )

        return exprs

    def _get_partition_cols(self, level_index: int, max_steps: int) -> List[ast.Expr]:
        query, funnelsFilter = self.context.query, self.context.funnelsFilter
        exclusions = funnelsFilter.exclusions
        series = query.series

        exprs: List[ast.Expr] = []

        for i in range(0, max_steps):
            exprs.append(ast.Field(chain=[f"step_{i}"]))

            if i < level_index:
                exprs.append(ast.Field(chain=[f"latest_{i}"]))

                # for field in self.extra_event_fields_and_properties:
                #     exprs.append(ast.Field(chain=[f'"{field}_{i}"']))

                for exclusion_id, exclusion in enumerate(exclusions or []):
                    if cast(int, exclusion.funnelFromStep) + 1 == i:
                        exprs.append(ast.Field(chain=[f"exclusion_{exclusion_id}_latest_{exclusion.funnelFromStep}"]))

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

                for exclusion_id, exclusion in enumerate(exclusions or []):
                    # exclusion starting at step i follows semantics of step i+1 in the query (since we're looking for exclusions after step i)
                    if cast(int, exclusion.funnelFromStep) + 1 == i:
                        exprs.append(
                            parse_expr(
                                f"min(exclusion_{exclusion_id}_latest_{exclusion.funnelFromStep}) over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) exclusion_{exclusion_id}_latest_{exclusion.funnelFromStep}"
                            )
                        )

        return exprs

    def _get_breakdown_expr(self, group_remaining=False) -> List[ast.Expr]:
        # SEE BELOW
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

    def _get_breakdown_prop(self, group_remaining=False) -> str:
        # SEE ABOVE
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
        return ""

    def _query_has_array_breakdown(self) -> bool:
        breakdown, breakdown_type = self.context.breakdownFilter.breakdown, self.context.breakdownFilter.breakdown_type
        return not isinstance(breakdown, str) and breakdown_type != "cohort"

    def _get_exclusion_condition(self) -> List[ast.Expr]:
        funnelsFilter = self.context.funnelsFilter
        windowInterval = self.context.funnelWindowInterval
        windowIntervalUnit = funnel_window_interval_unit_to_sql(self.context.funnelWindowIntervalUnit)

        if not funnelsFilter.exclusions:
            return []

        conditions: List[ast.Expr] = []

        for exclusion_id, exclusion in enumerate(funnelsFilter.exclusions):
            from_time = f"latest_{exclusion.funnelFromStep}"
            to_time = f"latest_{exclusion.funnelToStep}"
            exclusion_time = f"exclusion_{exclusion_id}_latest_{exclusion.funnelFromStep}"
            condition = parse_expr(
                f"if( {exclusion_time} > {from_time} AND {exclusion_time} < if(isNull({to_time}), {from_time} + INTERVAL {windowInterval} {windowIntervalUnit}, {to_time}), 1, 0)"
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
