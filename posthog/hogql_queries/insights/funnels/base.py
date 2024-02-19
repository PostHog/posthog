from abc import ABC
from functools import cached_property
from typing import Any, Dict, List, Optional, Tuple, Union, cast
import uuid
from posthog.clickhouse.materialized_columns.column import ColumnName
from posthog.constants import BREAKDOWN_VALUES_LIMIT
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.funnels.funnel_event_query import FunnelEventQuery
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.utils import (
    funnel_window_interval_unit_to_sql,
    get_breakdown_expr,
)
from posthog.hogql_queries.insights.utils.entities import is_equal, is_superset
from posthog.models.action.action import Action
from posthog.models.cohort.cohort import Cohort
from posthog.models.property.property import PropertyName
from posthog.queries.util import correct_result_for_sampling
from posthog.queries.breakdown_props import ALL_USERS_COHORT_ID, get_breakdown_cohort_name
from posthog.schema import (
    ActionsNode,
    BreakdownAttributionType,
    BreakdownType,
    EventsNode,
    FunnelExclusionActionsNode,
    FunnelTimeToConvertResults,
    StepOrderValue,
)
from posthog.types import EntityNode, ExclusionEntityNode
from rest_framework.exceptions import ValidationError


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

    @cached_property
    def breakdown_cohorts(self) -> List[Cohort]:
        team, breakdown = self.context.team, self.context.breakdown

        if isinstance(breakdown, list):
            cohorts = Cohort.objects.filter(team_id=team.pk, pk__in=[b for b in breakdown if b != "all"])
        else:
            cohorts = Cohort.objects.filter(team_id=team.pk, pk=breakdown)

        return list(cohorts)

    @cached_property
    def breakdown_cohorts_ids(self) -> List[int]:
        breakdown = self.context.breakdown

        ids = [int(cohort.pk) for cohort in self.breakdown_cohorts]

        if isinstance(breakdown, list) and "all" in breakdown:
            ids.append(ALL_USERS_COHORT_ID)

        return ids

    @cached_property
    def breakdown_values(self) -> List[int] | List[str] | List[List[str]]:
        # """
        # Returns the top N breakdown prop values for event/person breakdown

        # e.g. for Browser with limit 3 might return ['Chrome', 'Safari', 'Firefox', 'Other']
        # """
        team, query, funnelsFilter, breakdownType, breakdownFilter, breakdownAttributionType = (
            self.context.team,
            self.context.query,
            self.context.funnelsFilter,
            self.context.breakdownType,
            self.context.breakdownFilter,
            self.context.breakdownAttributionType,
        )

        use_all_funnel_entities = (
            breakdownAttributionType
            in [
                BreakdownAttributionType.first_touch,
                BreakdownAttributionType.last_touch,
            ]
            or funnelsFilter.funnelOrderType == StepOrderValue.unordered
        )
        first_entity = query.series[0]
        target_entity = first_entity
        if breakdownAttributionType == BreakdownAttributionType.step:
            assert isinstance(funnelsFilter.breakdownAttributionValue, int)
            target_entity = query.series[funnelsFilter.breakdownAttributionValue]

        if breakdownType == "cohort":
            return self.breakdown_cohorts_ids
        else:
            # get query params
            breakdown_expr = self._get_breakdown_expr()
            breakdown_limit_or_default = breakdownFilter.breakdown_limit or BREAKDOWN_VALUES_LIMIT
            offset = 0

            funnel_event_query = FunnelEventQuery(context=self.context)

            if use_all_funnel_entities:
                entity_expr = funnel_event_query._entity_expr(skip_entity_filter=False)
                prop_exprs = funnel_event_query._properties_expr()
            else:
                entity_expr = None
                # TODO implement for strict and ordered funnels
                # entity_params, entity_format_params = get_entity_filtering_params(
                #     allowed_entities=[target_entity],
                #     team_id=team.pk,
                #     table_name="e",
                #     person_id_joined_alias=person_id_joined_alias,
                #     person_properties_mode=person_properties_mode,
                #     hogql_context=filter.hogql_context,
                # )

                if target_entity.properties:
                    prop_exprs = [property_to_expr(target_entity.properties, team)]
                else:
                    prop_exprs = []

            where_exprs: List[ast.Expr | None] = [
                # entity filter
                entity_expr,
                # prop filter
                *prop_exprs,
                # date range filter
                funnel_event_query._date_range_expr(),
                # null persons filter
                parse_expr("notEmpty(e.person_id)"),
            ]

            # build query
            values_query = ast.SelectQuery(
                select=[ast.Alias(alias="value", expr=breakdown_expr), parse_expr("count(*) as count")],
                select_from=ast.JoinExpr(
                    table=ast.Field(chain=["events"]),
                    alias="e",
                ),
                where=ast.And(exprs=[expr for expr in where_exprs if expr is not None]),
                group_by=[ast.Field(chain=["value"])],
                order_by=[
                    ast.OrderExpr(expr=ast.Field(chain=["count"]), order="DESC"),
                    ast.OrderExpr(expr=ast.Field(chain=["value"]), order="DESC"),
                ],
                limit=ast.Constant(value=breakdown_limit_or_default + 1),
                offset=ast.Constant(value=offset),
            )

            if query.samplingFactor is not None:
                assert isinstance(values_query.select_from, ast.JoinExpr)
                values_query.select_from.sample = ast.SampleExpr(
                    sample_value=ast.RatioExpr(left=ast.Constant(value=query.samplingFactor))
                )

            # execute query
            results = execute_hogql_query(values_query, self.context.team).results
            if results is None:
                raise ValidationError("Apologies, there has been an error computing breakdown values.")
            return [row[0] for row in results[0:breakdown_limit_or_default]]

    def _get_breakdown_select_prop(self) -> List[ast.Expr]:
        breakdown, breakdownAttributionType, funnelsFilter = (
            self.context.breakdown,
            self.context.breakdownAttributionType,
            self.context.funnelsFilter,
        )

        if not breakdown:
            return []

        # breakdown prop
        prop_basic = ast.Alias(alias="prop_basic", expr=self._get_breakdown_expr())

        # breakdown attribution
        if breakdownAttributionType == BreakdownAttributionType.step:
            select_columns = []
            default_breakdown_selector = "[]" if self._query_has_array_breakdown() else "NULL"
            # get prop value from each step
            for index, _ in enumerate(self.context.query.series):
                select_columns.append(
                    parse_expr(f"if(step_{index} = 1, prop_basic, {default_breakdown_selector}) as prop_{index}")
                )

            final_select = parse_expr(f"prop_{funnelsFilter.breakdownAttributionValue} as prop")
            prop_window = parse_expr("groupUniqArray(prop) over (PARTITION by aggregation_target) as prop_vals")

            return [prop_basic, *select_columns, final_select, prop_window]
        elif breakdownAttributionType in [
            BreakdownAttributionType.first_touch,
            BreakdownAttributionType.last_touch,
        ]:
            prop_conditional = (
                "notEmpty(arrayFilter(x -> notEmpty(x), prop))"
                if self._query_has_array_breakdown()
                else "isNotNull(prop)"
            )

            aggregate_operation = (
                "argMinIf" if breakdownAttributionType == BreakdownAttributionType.first_touch else "argMaxIf"
            )

            breakdown_window_selector = f"{aggregate_operation}(prop, timestamp, {prop_conditional})"
            prop_window = parse_expr(f"{breakdown_window_selector} over (PARTITION by aggregation_target) as prop_vals")
            return [
                prop_basic,
                ast.Alias(alias="prop", expr=ast.Field(chain=["prop_basic"])),
                prop_window,
            ]
        else:
            # all_events
            return [
                prop_basic,
                ast.Alias(alias="prop", expr=ast.Field(chain=["prop_basic"])),
            ]

    def _get_breakdown_expr(self) -> ast.Expr:
        breakdown, breakdownType, breakdownFilter = (
            self.context.breakdown,
            self.context.breakdownType,
            self.context.breakdownFilter,
        )

        if breakdownType == "person":
            properties_column = "person.properties"
            return get_breakdown_expr(breakdown, properties_column)
        elif breakdownType == "event":
            properties_column = "properties"
            normalize_url = breakdownFilter.breakdown_normalize_url
            return get_breakdown_expr(breakdown, properties_column, normalize_url=normalize_url)
        elif breakdownType == "cohort":
            return ast.Field(chain=["value"])
        elif breakdownType == "group":
            properties_column = f"group_{breakdownFilter.breakdown_group_type_index}.properties"
            return get_breakdown_expr(breakdown, properties_column)
        elif breakdownType == "hogql":
            return ast.Alias(
                alias="value",
                expr=parse_expr(str(breakdown)),
            )
        else:
            raise ValidationError(detail=f"Unsupported breakdown type: {breakdownType}")

    def _format_results(
        self, results
    ) -> Union[FunnelTimeToConvertResults, List[Dict[str, Any]], List[List[Dict[str, Any]]]]:
        breakdown = self.context.breakdown

        if not results or len(results) == 0:
            return []

        if breakdown:
            return [self._format_single_funnel(res, with_breakdown=True) for res in results]
        else:
            return self._format_single_funnel(results[0])

    def _format_single_funnel(self, results, with_breakdown=False):
        max_steps = self.context.max_steps

        # Format of this is [step order, person count (that reached that step), array of person uuids]
        steps = []
        total_people = 0

        breakdown_value = results[-1]
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

            if with_breakdown:
                # breakdown will return a display ready value
                # breakdown_value will return the underlying id if different from display ready value (ex: cohort id)
                serialized_result.update(
                    {
                        "breakdown": (
                            get_breakdown_cohort_name(breakdown_value)
                            if self.context.breakdownFilter.breakdown_type == "cohort"
                            else breakdown_value
                        ),
                        "breakdown_value": breakdown_value,
                    }
                )
                # important to not try and modify this value any how - as these
                # are keys for fetching persons

                # # Add in the breakdown to people urls as well
                # converted_people_filter = converted_people_filter.shallow_clone(
                #     {"funnel_step_breakdown": breakdown_value}
                # )
                # dropped_people_filter = dropped_people_filter.shallow_clone({"funnel_step_breakdown": breakdown_value})

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
            "action_id": step.event if isinstance(step, EventsNode) else step.id,
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
        query, funnelsFilter, breakdown, breakdownType, breakdownAttributionType = (
            self.context.query,
            self.context.funnelsFilter,
            self.context.breakdown,
            self.context.breakdownType,
            self.context.breakdownAttributionType,
        )
        entities_to_use = entities or query.series

        # extra_fields = []

        # for prop in self._include_properties:
        #     extra_fields.append(prop)

        funnel_events_query = FunnelEventQuery(context=self.context).to_query(skip_entity_filter=skip_entity_filter)
        # funnel_events_query, params = FunnelEventQuery(
        #     extra_fields=[*self._extra_event_fields, *extra_fields],
        #     extra_event_properties=self._extra_event_properties,
        # ).get_query(entities_to_use, entity_name, skip_entity_filter=skip_entity_filter)

        all_step_cols: List[ast.Expr] = []
        for index, entity in enumerate(entities_to_use):
            step_cols = self._get_step_col(entity, index, entity_name)
            all_step_cols.extend(step_cols)

        for exclusion_id, entity in enumerate(funnelsFilter.exclusions or []):
            step_cols = self._get_step_col(entity, entity.funnelFromStep, entity_name, f"exclusion_{exclusion_id}_")
            # every exclusion entity has the form: exclusion_<id>_step_i & timestamp exclusion_<id>_latest_i
            # where i is the starting step for exclusion on that entity
            all_step_cols.extend(step_cols)

        breakdown_select_prop = self._get_breakdown_select_prop()

        if breakdown_select_prop:
            all_step_cols.extend(breakdown_select_prop)

        funnel_events_query.select = [*funnel_events_query.select, *all_step_cols]

        if breakdown and breakdownType == BreakdownType.cohort:
            if funnel_events_query.select_from is None:
                raise ValidationError("Apologies, there was an error adding cohort breakdowns to the query.")
            funnel_events_query.select_from.next_join = self._get_cohort_breakdown_join()

        if not skip_step_filter:
            assert isinstance(funnel_events_query.where, ast.Expr)
            steps_conditions = self._get_steps_conditions(length=len(entities_to_use))
            funnel_events_query.where = ast.And(exprs=[funnel_events_query.where, steps_conditions])

        if breakdown and breakdownAttributionType != BreakdownAttributionType.all_events:
            # ALL_EVENTS attribution is the old default, which doesn't need the subquery
            return self._add_breakdown_attribution_subquery(funnel_events_query)

        return funnel_events_query

    def _get_cohort_breakdown_join(self) -> ast.JoinExpr:
        breakdown = self.context.breakdown

        cohort_queries: List[ast.SelectQuery] = []

        for cohort in self.breakdown_cohorts:
            query = parse_select(
                f"select id as cohort_person_id, {cohort.pk} as value from persons where id in cohort {cohort.pk}"
            )
            assert isinstance(query, ast.SelectQuery)
            cohort_queries.append(query)

        if isinstance(breakdown, list) and "all" in breakdown:
            all_query = FunnelEventQuery(context=self.context).to_query()
            all_query.select = [
                ast.Alias(alias="cohort_person_id", expr=ast.Field(chain=["person_id"])),
                ast.Alias(alias="value", expr=ast.Constant(value=ALL_USERS_COHORT_ID)),
            ]
            cohort_queries.append(all_query)

        return ast.JoinExpr(
            join_type="INNER JOIN",
            table=ast.SelectUnionQuery(select_queries=cohort_queries),
            alias="cohort_join",
            constraint=ast.JoinConstraint(
                expr=ast.CompareOperation(
                    left=ast.Field(chain=[FunnelEventQuery.EVENT_TABLE_ALIAS, "person_id"]),
                    right=ast.Field(chain=["cohort_join", "cohort_person_id"]),
                    op=ast.CompareOperationOp.Eq,
                )
            ),
        )

    def _add_breakdown_attribution_subquery(self, inner_query: ast.SelectQuery) -> ast.SelectQuery:
        breakdown, breakdownAttributionType = (
            self.context.breakdown,
            self.context.breakdownAttributionType,
        )

        if breakdownAttributionType in [
            BreakdownAttributionType.first_touch,
            BreakdownAttributionType.last_touch,
        ]:
            # When breaking down by first/last touch, each person can only have one prop value
            # so just select that. Except for the empty case, where we select the default.

            if self._query_has_array_breakdown():
                default_breakdown_value = f"""[{','.join(["''" for _ in range(len(breakdown or []))])}]"""
                # default is [''] when dealing with a single breakdown array, otherwise ['', '', ...., '']
                breakdown_selector = parse_expr(
                    f"if(notEmpty(arrayFilter(x -> notEmpty(x), prop_vals)), prop_vals, {default_breakdown_value})"
                )
            else:
                breakdown_selector = ast.Field(chain=["prop_vals"])

            return ast.SelectQuery(
                select=[ast.Field(chain=["*"]), ast.Alias(alias="prop", expr=breakdown_selector)],
                select_from=ast.JoinExpr(table=inner_query),
            )

        # When breaking down by specific step, each person can have multiple prop values
        # so array join those to each event
        query = ast.SelectQuery(
            select=[ast.Field(chain=["*"]), ast.Field(chain=["prop"])],
            select_from=ast.JoinExpr(table=inner_query),
            array_join_op="ARRAY JOIN",
            array_join_list=[ast.Alias(alias="prop", expr=ast.Field(chain=["prop_vals"]))],
        )

        if self._query_has_array_breakdown():
            query.where = ast.CompareOperation(
                left=ast.Field(chain=["prop"]), right=ast.Array(exprs=[]), op=ast.CompareOperationOp.NotEq
            )

        return query

    def _get_steps_conditions(self, length: int) -> ast.Expr:
        step_conditions: List[ast.Expr] = []

        for index in range(length):
            step_conditions.append(parse_expr(f"step_{index} = 1"))

        for exclusion_id, entity in enumerate(self.context.funnelsFilter.exclusions or []):
            step_conditions.append(parse_expr(f"exclusion_{exclusion_id}_step_{entity.funnelFromStep} = 1"))

        return ast.Or(exprs=step_conditions)

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

    def _get_breakdown_prop_expr(self, group_remaining=False) -> List[ast.Expr]:
        # SEE BELOW for a string implementation of the following
        breakdown, breakdownType = self.context.breakdown, self.context.breakdownType

        if breakdown:
            other_aggregation = "['Other']" if self._query_has_array_breakdown() else "'Other'"
            if group_remaining and breakdownType in [
                BreakdownType.person,
                BreakdownType.event,
                BreakdownType.group,
            ]:
                breakdown_values = self._get_breakdown_conditions()
                return [parse_expr(f"if(has({breakdown_values}, prop), prop, {other_aggregation}) as prop")]
            else:
                # Cohorts don't have "Other" aggregation
                return [ast.Field(chain=["prop"])]
        else:
            return []

    def _get_breakdown_prop(self, group_remaining=False) -> str:
        # SEE ABOVE for an ast implementation of the following
        breakdown = self.context.breakdown

        if breakdown:
            # TODO: implement the below if group_remaining can ever be true
            # breakdown_values = self._get_breakdown_conditions()
            # other_aggregation = "['Other']" if self._query_has_array_breakdown() else "'Other'"
            # if group_remaining and breakdownFilter.breakdown_type in [
            #     BreakdownType.person,
            #     BreakdownType.event,
            #     BreakdownType.group,
            # ]:
            #     return f", if(has({breakdown_values}, prop), prop, {other_aggregation}) as prop"
            # else:
            #     # Cohorts don't have "Other" aggregation
            return ", prop"
        else:
            return ""

    def _get_breakdown_conditions(self) -> Optional[List[int] | List[str] | List[List[str]]]:
        """
        For people, pagination sets the offset param, which is common across filters
        and gives us the wrong breakdown values here, so we override it.
        For events, depending on the attribution type, we either look at only one entity,
        or all of them in the funnel.
        if this is a multi property breakdown then the breakdown values are misleading
        e.g. [Chrome, Safari], [95, 15] doesn't make clear that Chrome 15 isn't valid but Safari 15 is
        so the generated list here must be [[Chrome, 95], [Safari, 15]]
        """
        if self.context.breakdown:
            return self.breakdown_values

        return None

    def _query_has_array_breakdown(self) -> bool:
        breakdown, breakdownType = self.context.breakdown, self.context.breakdownType
        return not isinstance(breakdown, str) and breakdownType != "cohort"

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
