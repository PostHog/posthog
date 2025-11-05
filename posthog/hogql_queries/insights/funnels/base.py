import uuid
import itertools
from abc import ABC
from functools import cached_property
from typing import Any, Optional, Union, cast

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    BreakdownAttributionType,
    BreakdownType,
    DataWarehouseNode,
    EventsNode,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    FunnelMathType,
    FunnelTimeToConvertResults,
    FunnelVizType,
    StepOrderValue,
)

from posthog.hogql import ast
from posthog.hogql.constants import get_breakdown_limit_for_context
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import action_to_expr, property_to_expr

from posthog.clickhouse.materialized_columns import ColumnName
from posthog.hogql_queries.insights.funnels.funnel_aggregation_operations import FirstTimeForUserAggregationQuery
from posthog.hogql_queries.insights.funnels.funnel_event_query import FunnelEventQuery
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.utils import funnel_window_interval_unit_to_sql, get_breakdown_expr
from posthog.hogql_queries.insights.utils.entities import is_equal, is_superset
from posthog.models.action.action import Action
from posthog.models.cohort.cohort import Cohort
from posthog.models.property.property import PropertyName
from posthog.queries.breakdown_props import ALL_USERS_COHORT_ID, get_breakdown_cohort_name
from posthog.queries.util import correct_result_for_sampling
from posthog.types import EntityNode, ExclusionEntityNode

JOIN_ALGOS = "auto"


class FunnelBase(ABC):
    context: FunnelQueryContext

    _extra_event_fields: list[ColumnName]
    _extra_event_properties: list[PropertyName]

    def __init__(self, context: FunnelQueryContext):
        self.context = context

        self._extra_event_fields: list[ColumnName] = []
        self._extra_event_properties: list[PropertyName] = []

        if (
            hasattr(self.context, "actorsQuery")
            and self.context.actorsQuery is not None
            and self.context.actorsQuery.includeRecordings
        ):
            self._extra_event_fields = ["uuid"]
            self._extra_event_properties = ["$session_id", "$window_id"]

        # validate funnel steps range
        max_series_index = len(self.context.query.series) - 1
        if self.context.funnelsFilter.funnelFromStep is not None:
            if not (0 <= self.context.funnelsFilter.funnelFromStep <= max_series_index - 1):
                raise ValidationError(
                    f"funnelFromStep is out of bounds. It must be between 0 and {max_series_index - 1}."
                )

        if self.context.funnelsFilter.funnelToStep is not None:
            if not (1 <= self.context.funnelsFilter.funnelToStep <= max_series_index):
                raise ValidationError(f"funnelToStep is out of bounds. It must be between 1 and {max_series_index}.")

            if (
                self.context.funnelsFilter.funnelFromStep is not None
                and self.context.funnelsFilter.funnelFromStep >= self.context.funnelsFilter.funnelToStep
            ):
                raise ValidationError(
                    "Funnel step range is invalid. funnelToStep should be greater than funnelFromStep."
                )

        # validate exclusions
        if self.context.funnelsFilter.exclusions is not None:
            for exclusion in self.context.funnelsFilter.exclusions:
                if exclusion.funnelFromStep >= exclusion.funnelToStep:
                    raise ValidationError(
                        "Exclusion event range is invalid. End of range should be greater than start."
                    )

                if exclusion.funnelFromStep >= len(self.context.query.series) - 1:
                    raise ValidationError(
                        "Exclusion event range is invalid. Start of range is greater than number of steps."
                    )

                if exclusion.funnelToStep > len(self.context.query.series) - 1:
                    raise ValidationError(
                        "Exclusion event range is invalid. End of range is greater than number of steps."
                    )

                for entity in self.context.query.series[exclusion.funnelFromStep : exclusion.funnelToStep + 1]:
                    if is_equal(entity, exclusion) or is_superset(entity, exclusion):
                        raise ValidationError("Exclusion steps cannot contain an event that's part of funnel steps.")

        has_optional_steps = any(getattr(node, "optionalInFunnel", False) for node in self.context.query.series)

        if has_optional_steps:
            # validate that optional steps are only allowed in Ordered Steps funnels
            allows_optional_steps = (
                self.context.funnelsFilter.funnelVizType in (FunnelVizType.STEPS, None)
                and self.context.funnelsFilter.funnelOrderType != StepOrderValue.UNORDERED
            )
            if not allows_optional_steps:
                raise ValidationError(
                    'Optional funnel steps are only supported in funnels with step order Sequential or Strict and the graph type "Conversion Steps".'
                )

            # validate that the first step is not optional
            if self.context.query.series and getattr(self.context.query.series[0], "optionalInFunnel", False):
                raise ValidationError("The first step of a funnel cannot be optional.")

            # Validate that an optional step never follows a required step that is exactly the same right after it
            # In that case, the optional step will show up as never converting.
            # Not trying to be overly clever here - putting filters in different order or using SQL queries that are slightly different could
            # get around this, but want to stop the naive case from spawning support issues.
            for i, j in itertools.pairwise(self.context.query.series):
                if (
                    (is_equal(i, j) or is_superset(j, i))
                    and getattr(i, "optionalInFunnel", True)
                    and not getattr(j, "optionalInFunnel", False)
                ):
                    raise ValidationError("An optional step cannot be the same as the following required step.")

    def get_query(self) -> ast.SelectQuery:
        raise NotImplementedError()

    def get_step_counts_query(self) -> ast.SelectQuery:
        raise NotImplementedError()

    def get_step_counts_without_aggregation_query(self) -> ast.SelectQuery:
        raise NotImplementedError()

    # This is a simple heuristic to reduce the number of events we look at in UDF funnels (thus are serialized and sent over)
    # We remove an event if it matches one or zero steps and there was already the same type of event before and after it (that don't have the same timestamp)
    # arrayRotateRight turns [1,2,3] into [3,1,2]
    # arrayRotateLeft turns [1,2,3] into [2,3,1]
    # For some reason, using these uses much less memory than using indexing in clickhouse to check the previous and next element
    def _udf_event_array_filter(self, timestamp_index: int, prop_val_index: int, steps_index: int):
        return f"""arrayFilter(
                    (x, x_before, x_after) -> not (
                        length(x.{steps_index}) <= 1
                        and x.{steps_index} == x_before.{steps_index}
                        and x.{steps_index} == x_after.{steps_index}
                        and x.{prop_val_index} == x_before.{prop_val_index}
                        and x.{prop_val_index} == x_after.{prop_val_index}
                        and x.{timestamp_index} > x_before.{timestamp_index}
                        and x.{timestamp_index} < x_after.{timestamp_index}),
                    events_array,
                    arrayRotateRight(events_array, 1),
                    arrayRotateLeft(events_array, 1))"""

    @cached_property
    def breakdown_cohorts(self) -> list[Cohort]:
        team, breakdown = self.context.team, self.context.breakdown

        if isinstance(breakdown, list):
            cohorts = Cohort.objects.filter(
                team__project_id=team.project_id, pk__in=[b for b in breakdown if b != "all"]
            )
        else:
            cohorts = Cohort.objects.filter(team__project_id=team.project_id, pk=breakdown)

        return list(cohorts)

    @cached_property
    def breakdown_cohorts_ids(self) -> list[int]:
        breakdown = self.context.breakdown

        ids = [int(cohort.pk) for cohort in self.breakdown_cohorts]

        if isinstance(breakdown, list) and "all" in breakdown:
            ids.append(ALL_USERS_COHORT_ID)

        return ids

    def _get_breakdown_select_prop(self, for_udf=False) -> list[ast.Expr]:
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
        if breakdownAttributionType == BreakdownAttributionType.STEP:
            select_columns = []
            default_breakdown_selector = "[]" if self._query_has_array_breakdown() else "NULL"

            # Unordered funnels can have any step be the Nth step
            if for_udf and funnelsFilter.funnelOrderType == StepOrderValue.UNORDERED:
                final_select = parse_expr(f"prop_basic as prop")
            else:
                # get prop value from each step
                for index, _ in enumerate(self.context.query.series):
                    select_columns.append(
                        parse_expr(f"if(step_{index} = 1, prop_basic, {default_breakdown_selector}) as prop_{index}")
                    )

                final_select = parse_expr(f"prop_{funnelsFilter.breakdownAttributionValue} as prop")

            if for_udf:
                return [prop_basic, *select_columns, final_select]

            prop_window = parse_expr("groupUniqArray(prop) over (PARTITION by aggregation_target) as prop_vals")
            return [prop_basic, *select_columns, final_select, prop_window]
        elif breakdownAttributionType in [
            BreakdownAttributionType.FIRST_TOUCH,
            BreakdownAttributionType.LAST_TOUCH,
        ]:
            prop_conditional = (
                "notEmpty(arrayFilter(x -> notEmpty(x), prop))"
                if self._query_has_array_breakdown()
                else "isNotNull(prop)"
            )

            aggregate_operation = (
                "argMinIf" if breakdownAttributionType == BreakdownAttributionType.FIRST_TOUCH else "argMaxIf"
            )

            breakdown_window_selector = f"{aggregate_operation}(prop, timestamp, {prop_conditional})"
            if for_udf:
                return [prop_basic, ast.Alias(alias="prop", expr=ast.Field(chain=["prop_basic"]))]
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

        assert breakdown is not None

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
        elif breakdownType == "hogql" or breakdownType == "event_metadata":
            assert isinstance(breakdown, list)
            return ast.Alias(
                alias="value",
                expr=ast.Array(exprs=[parse_expr(str(value)) for value in breakdown]),
            )
        elif breakdownType == "data_warehouse_person_property" and isinstance(breakdown, str):
            return ast.Field(chain=["person", *breakdown.split(".")])
        else:
            raise ValidationError(detail=f"Unsupported breakdown type: {breakdownType}")

    def _format_results(
        self, results
    ) -> Union[FunnelTimeToConvertResults, list[dict[str, Any]], list[list[dict[str, Any]]]]:
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

            steps.append(serialized_result)

        return steps[::-1]  # reverse

    def _serialize_step(
        self,
        step: ActionsNode | EventsNode | DataWarehouseNode,
        count: int,
        index: int,
        people: Optional[list[uuid.UUID]] = None,
        sampling_factor: Optional[float] = None,
    ) -> dict[str, Any]:
        if isinstance(step, DataWarehouseNode):
            raise ValidationError(
                "Data warehouse tables are not supported in funnels just yet. For now, please try this funnel without the data warehouse-based step."
            )

        if self.context.funnelsFilter.funnelOrderType == StepOrderValue.UNORDERED:
            return {
                "action_id": None,
                "name": f"Completed {index + 1} step{'s' if index != 0 else ''}",
                "custom_name": None,
                "order": index,
                "people": people if people else [],
                "count": correct_result_for_sampling(count, sampling_factor),
                "type": "events" if isinstance(step, EventsNode) else "actions",
            }

        action_id: Optional[str | int]
        if isinstance(step, EventsNode):
            name = step.event
            action_id = step.event
            type = "events"
        else:
            action = Action.objects.get(pk=step.id, team__project_id=self.context.team.project_id)
            name = action.name
            action_id = step.id
            type = "actions"

        return {
            "action_id": action_id,
            "name": name,
            "custom_name": step.custom_name,
            "order": index,
            "people": people if people else [],
            "count": correct_result_for_sampling(count, sampling_factor),
            "type": type,
        }

    @property
    def extra_event_fields_and_properties(self):
        return self._extra_event_fields + self._extra_event_properties

    @property
    def _absolute_actors_step(self) -> Optional[int]:
        """The actor query's 1-indexed target step converted to our 0-indexed SQL form. Never a negative integer."""
        if self.context.actorsQuery is None or self.context.actorsQuery.funnelStep is None:
            return None

        target_step = self.context.actorsQuery.funnelStep
        if target_step < 0:
            if target_step == -1:
                raise ValueError(
                    "The first valid drop-off argument for funnelStep is -2. -2 refers to persons who performed "
                    "the first step but never made it to the second."
                )
            return abs(target_step) - 2
        elif target_step == 0:
            raise ValueError("Funnel steps are 1-indexed, so step 0 doesn't exist")
        else:
            return target_step - 1

    def _get_inner_event_query(
        self,
        entities: list[EntityNode] | None = None,
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

        extra_fields: list[str] = []

        for prop in self.context.includeProperties:
            extra_fields.append(prop)

        funnel_events_query = FunnelEventQuery(
            context=self.context,
            extra_fields=[*self._extra_event_fields, *extra_fields],
            extra_event_properties=self._extra_event_properties,
        ).to_query(
            skip_entity_filter=skip_entity_filter,
        )
        # funnel_events_query, params = FunnelEventQuery(
        #     extra_fields=[*self._extra_event_fields, *extra_fields],
        #     extra_event_properties=self._extra_event_properties,
        # ).get_query(entities_to_use, entity_name, skip_entity_filter=skip_entity_filter)

        all_step_cols: list[ast.Expr] = []
        for index, entity in enumerate(entities_to_use):
            step_cols = self._get_step_col(entity, index, entity_name)
            all_step_cols.extend(step_cols)

        for exclusion_id, excluded_entity in enumerate(funnelsFilter.exclusions or []):
            step_cols = self._get_step_col(
                excluded_entity, excluded_entity.funnelFromStep, entity_name, f"exclusion_{exclusion_id}_"
            )
            # every exclusion entity has the form: exclusion_<id>_step_i & timestamp exclusion_<id>_latest_i
            # where i is the starting step for exclusion on that entity
            all_step_cols.extend(step_cols)

        breakdown_select_prop = self._get_breakdown_select_prop()

        if breakdown_select_prop:
            all_step_cols.extend(breakdown_select_prop)

        funnel_events_query.select = [*funnel_events_query.select, *all_step_cols]

        if breakdown and breakdownType == BreakdownType.COHORT:
            if funnel_events_query.select_from is None:
                raise ValidationError("Apologies, there was an error adding cohort breakdowns to the query.")
            funnel_events_query.select_from.next_join = self._get_cohort_breakdown_join()

        if not skip_step_filter:
            assert isinstance(funnel_events_query.where, ast.Expr)
            steps_conditions = self._get_steps_conditions(length=len(entities_to_use))
            funnel_events_query.where = ast.And(exprs=[funnel_events_query.where, steps_conditions])

        if breakdown and breakdownAttributionType != BreakdownAttributionType.ALL_EVENTS:
            # ALL_EVENTS attribution is the old default, which doesn't need the subquery
            return self._add_breakdown_attribution_subquery(funnel_events_query)

        return funnel_events_query

    # This version of the inner event query modifies how exclusions are returned to
    # make them behave more like steps. It returns a boolean "exclusion_{0..n}" for each event
    def _get_inner_event_query_for_udf(
        self,
        entities: list[EntityNode] | None = None,
        entity_name="events",
        skip_entity_filter=False,
        skip_step_filter=False,
    ) -> ast.SelectQuery:
        query, funnelsFilter, breakdown, breakdownType = (
            self.context.query,
            self.context.funnelsFilter,
            self.context.breakdown,
            self.context.breakdownType,
        )
        entities_to_use = entities or query.series

        extra_fields: list[str] = []

        for prop in self.context.includeProperties:
            extra_fields.append(prop)

        funnel_events_query = FunnelEventQuery(
            context=self.context, extra_fields=[*self.extra_event_fields_and_properties, *extra_fields]
        ).to_query(
            skip_entity_filter=skip_entity_filter,
        )

        all_step_cols: list[ast.Expr] = []
        all_exclusions: list[list[FunnelExclusionEventsNode | FunnelExclusionActionsNode]] = []
        for index, entity in enumerate(entities_to_use):
            step_cols = self._get_step_col(entity, index, entity_name, for_udf=True)
            all_step_cols.extend(step_cols)
            all_exclusions.append([])

        if funnelsFilter.exclusions:
            for excluded_entity in funnelsFilter.exclusions:
                for i in range(excluded_entity.funnelFromStep + 1, excluded_entity.funnelToStep + 1):
                    all_exclusions[i].append(excluded_entity)

            for index, exclusions in enumerate(all_exclusions):
                exclusion_col_expr = self._get_exclusions_col(exclusions, index, entity_name)
                all_step_cols.append(exclusion_col_expr)

        breakdown_select_prop = self._get_breakdown_select_prop(for_udf=True)

        if breakdown_select_prop:
            all_step_cols.extend(breakdown_select_prop)

        funnel_events_query.select = [*funnel_events_query.select, *all_step_cols]

        if breakdown and breakdownType == BreakdownType.COHORT:
            assert funnel_events_query.select_from is not None
            funnel_events_query.select_from.next_join = self._get_cohort_breakdown_join()

        if not skip_step_filter:
            assert isinstance(funnel_events_query.where, ast.Expr)
            steps_conditions = self._get_steps_conditions_for_udf(all_exclusions, length=len(entities_to_use))
            funnel_events_query.where = ast.And(exprs=[funnel_events_query.where, steps_conditions])

        return funnel_events_query

    def _get_exclusions_col(
        self,
        exclusions: list[ExclusionEntityNode],
        index: int,
        entity_name: str,
    ) -> ast.Expr:
        if not exclusions:
            return parse_expr(f"0 as exclusion_{index}")
        conditions = [self._build_step_query(exclusion, index, entity_name, "") for exclusion in exclusions]
        return parse_expr(
            f"if({{condition}}, 1, 0) as exclusion_{index}", placeholders={"condition": ast.Or(exprs=conditions)}
        )

    def _get_cohort_breakdown_join(self) -> ast.JoinExpr:
        breakdown = self.context.breakdown

        cohort_queries: list[ast.SelectQuery] = []

        for cohort in self.breakdown_cohorts:
            query = parse_select(
                f"select person_id as cohort_person_id, {cohort.pk} as value from cohort_people where person_id in cohort {cohort.pk}"
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
            table=ast.SelectSetQuery.create_from_queries(cohort_queries, "UNION ALL"),
            alias="cohort_join",
            constraint=ast.JoinConstraint(
                expr=ast.CompareOperation(
                    left=ast.Field(chain=[FunnelEventQuery.EVENT_TABLE_ALIAS, "person_id"]),
                    right=ast.Field(chain=["cohort_join", "cohort_person_id"]),
                    op=ast.CompareOperationOp.Eq,
                ),
                constraint_type="ON",
            ),
        )

    def _add_breakdown_attribution_subquery(self, inner_query: ast.SelectQuery) -> ast.SelectQuery:
        breakdown, breakdownAttributionType = (
            self.context.breakdown,
            self.context.breakdownAttributionType,
        )

        if breakdownAttributionType in [
            BreakdownAttributionType.FIRST_TOUCH,
            BreakdownAttributionType.LAST_TOUCH,
        ]:
            # When breaking down by first/last touch, each person can only have one prop value
            # so just select that. Except for the empty case, where we select the default.

            if self._query_has_array_breakdown():
                assert isinstance(breakdown, list)
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

    def get_breakdown_limit(self):
        return self.context.breakdownFilter.breakdown_limit or get_breakdown_limit_for_context(
            self.context.limit_context
        )

    # Wrap funnel query in another query to determine the top X breakdowns, and bucket all others into "Other" bucket
    def _breakdown_other_subquery(self) -> ast.SelectQuery:
        max_steps = self.context.max_steps
        row_number = ast.Alias(
            alias="row_number",
            expr=ast.WindowFunction(
                name="row_number",
                over_expr=ast.WindowExpr(
                    order_by=[ast.OrderExpr(expr=ast.Field(chain=[f"step_{max_steps}"]), order="DESC")]
                    # TODO: this function doesn't support multiple order_by for some reason
                    # order_by=[ast.OrderExpr(expr=ast.Field(chain=[f"step_{i}"]), order="DESC") for i in range(max_steps, 0, -1)],
                ),
            ),
        )
        select_query = ast.SelectQuery(
            select=[
                *self._get_count_columns(max_steps),
                *self._get_step_time_array(max_steps),
                *self._get_breakdown_prop_expr(),
                row_number,
            ],
            select_from=ast.JoinExpr(table=self.get_step_counts_query()),
        )
        select_query.group_by = [ast.Field(chain=["prop"])]
        other_aggregation = "['Other']" if self._query_has_array_breakdown() else "'Other'"

        final_prop = ast.Alias(
            alias="final_prop",
            expr=parse_expr(
                f"if(row_number < {self.get_breakdown_limit() + 1}, prop, {other_aggregation})",
            ),
        )
        return ast.SelectQuery(
            select=[
                *self._get_sum_step_columns(max_steps),
                *self._get_step_time_array_avgs(max_steps),
                *self._get_step_time_array_median(max_steps),
                final_prop,
            ],
            select_from=ast.JoinExpr(table=select_query),
            group_by=[ast.Field(chain=["final_prop"])],
            limit=ast.Constant(value=self.get_breakdown_limit() + 1),
        )

    def _get_steps_conditions(self, length: int) -> ast.Expr:
        step_conditions: list[ast.Expr] = []

        for index in range(length):
            step_conditions.append(parse_expr(f"step_{index} = 1"))

        for exclusion_id, entity in enumerate(self.context.funnelsFilter.exclusions or []):
            step_conditions.append(parse_expr(f"exclusion_{exclusion_id}_step_{entity.funnelFromStep} = 1"))

        return ast.Or(exprs=step_conditions)

    def _get_steps_conditions_for_udf(self, exclusions, length: int) -> ast.Expr:
        step_conditions: list[ast.Expr] = []

        for index in range(length):
            step_conditions.append(parse_expr(f"step_{index} = 1"))
            if exclusions[index]:
                step_conditions.append(parse_expr(f"exclusion_{index} = 1"))

        return ast.Or(exprs=step_conditions)

    def _get_step_col(
        self,
        entity: EntityNode | ExclusionEntityNode,
        index: int,
        entity_name: str,
        step_prefix: str = "",
        for_udf: bool = False,
    ) -> list[ast.Expr]:
        # step prefix is used to distinguish actual steps, and exclusion steps
        # without the prefix, we get the same parameter binding for both, which borks things up
        step_cols: list[ast.Expr] = []
        condition = self._build_step_query(entity, index, entity_name, step_prefix)
        step_cols.append(
            parse_expr(f"if({{condition}}, 1, 0) as {step_prefix}step_{index}", placeholders={"condition": condition})
        )
        if not for_udf:
            step_cols.append(
                parse_expr(f"if({step_prefix}step_{index} = 1, timestamp, null) as {step_prefix}latest_{index}")
            )

            for field in self.extra_event_fields_and_properties:
                step_cols.append(
                    parse_expr(f'if({step_prefix}step_{index} = 1, "{field}", null) as "{step_prefix}{field}_{index}"')
                )

        return step_cols

    def _build_step_query(
        self,
        entity: EntityNode | ExclusionEntityNode,
        index: int,
        entity_name: str,
        step_prefix: str,
    ) -> ast.Expr:
        filters: list[ast.Expr] = []

        if isinstance(entity, ActionsNode) or isinstance(entity, FunnelExclusionActionsNode):
            # action
            action = Action.objects.get(pk=int(entity.id), team__project_id=self.context.team.project_id)
            event_expr = action_to_expr(action)
        elif isinstance(entity, DataWarehouseNode):
            raise ValidationError(
                "Data warehouse tables are not supported in funnels just yet. For now, please try this funnel without the data warehouse-based step."
            )
        elif entity.event is None:
            # all events
            event_expr = ast.Constant(value=1)
        else:
            # event
            event_expr = parse_expr("event = {event}", {"event": ast.Constant(value=entity.event)})

        filters.append(event_expr)

        filter_expr: ast.Expr | None = None
        if entity.properties is not None and entity.properties != []:
            # add property filters
            filter_expr = property_to_expr(entity.properties, self.context.team)
            filters.append(filter_expr)

        if entity.math == FunnelMathType.FIRST_TIME_FOR_USER:
            subquery = FirstTimeForUserAggregationQuery(self.context, filter_expr, event_expr).to_query()
            first_time_filter = ast.CompareOperation(
                left=ast.Field(chain=["e", "uuid"]), right=subquery, op=ast.CompareOperationOp.GlobalIn
            )
            return ast.And(exprs=[*filters, first_time_filter])
        elif entity.math == FunnelMathType.FIRST_TIME_FOR_USER_WITH_FILTERS:
            subquery = FirstTimeForUserAggregationQuery(
                self.context, ast.Constant(value=1), ast.And(exprs=filters)
            ).to_query()
            first_time_filter = ast.CompareOperation(
                left=ast.Field(chain=["e", "uuid"]), right=subquery, op=ast.CompareOperationOp.GlobalIn
            )
            return ast.And(exprs=[*filters, first_time_filter])
        elif len(filters) > 1:
            return ast.And(exprs=filters)
        return filters[0]

    def _get_timestamp_outer_select(self) -> list[ast.Expr]:
        if self.context.includePrecedingTimestamp:
            return [ast.Field(chain=["max_timestamp"]), ast.Field(chain=["min_timestamp"])]
        elif self.context.includeTimestamp:
            return [ast.Field(chain=["timestamp"])]
        else:
            return []

    def _get_funnel_person_step_condition(self) -> ast.Expr:
        actorsQuery, breakdownType, max_steps = (
            self.context.actorsQuery,
            self.context.breakdownType,
            self.context.max_steps,
        )
        assert actorsQuery is not None

        funnelStep = actorsQuery.funnelStep
        funnelStepBreakdown = actorsQuery.funnelStepBreakdown

        if funnelStep is None:
            raise ValueError("Missing funnelStep in actors query")

        conditions: list[ast.Expr] = []

        if funnelStep >= 0:
            step_nums = list(range(funnelStep, max_steps + 1))
            conditions.append(parse_expr(f"steps IN {step_nums}"))
        else:
            step_num = abs(funnelStep) - 1
            conditions.append(parse_expr(f"steps = {step_num}"))

        if funnelStepBreakdown is not None:
            if isinstance(funnelStepBreakdown, int) and breakdownType != "cohort":
                funnelStepBreakdown = str(funnelStepBreakdown)

            conditions.append(
                parse_expr(
                    "arrayFlatten(array(prop)) = arrayFlatten(array({funnelStepBreakdown}))",
                    {"funnelStepBreakdown": ast.Constant(value=funnelStepBreakdown)},
                )
            )

        return ast.And(exprs=conditions)

    def _include_matched_events(self):
        return (
            hasattr(self.context, "actorsQuery")
            and self.context.actorsQuery is not None
            and self.context.actorsQuery.includeRecordings
        )

    def _get_funnel_person_step_events(self) -> list[ast.Expr]:
        if self._include_matched_events():
            if self.context.includeFinalMatchingEvents:
                # Always returns the user's final step of the funnel
                return [parse_expr("final_matching_events as matching_events")]

            absolute_actors_step = self._absolute_actors_step
            if absolute_actors_step is None:
                raise ValueError("Missing funnelStep actors query property")
            return [parse_expr(f"step_{absolute_actors_step}_matching_events as matching_events")]
        return []

    def _get_count_columns(self, max_steps: int) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []

        for i in range(max_steps):
            exprs.append(parse_expr(f"countIf(steps = {i + 1}) as step_{i + 1}"))

        return exprs

    def _get_sum_step_columns(self, max_steps: int) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []

        for i in range(max_steps):
            exprs.append(parse_expr(f"sum(step_{i + 1}) as step_{i + 1}"))

        return exprs

    def _get_step_time_names(self, max_steps: int) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []

        for i in range(1, max_steps):
            exprs.append(parse_expr(f"step_{i}_conversion_time"))

        return exprs

    def _get_final_matching_event(self, max_steps: int) -> list[ast.Expr]:
        statement = None
        for i in range(max_steps - 1, -1, -1):
            if i == max_steps - 1:
                statement = f"if(isNull(latest_{i}),step_{i-1}_matching_event,step_{i}_matching_event)"
            elif i == 0:
                statement = f"if(isNull(latest_0),(null,null,null,null),{statement})"
            else:
                statement = f"if(isNull(latest_{i}),step_{i-1}_matching_event,{statement})"
        return [parse_expr(f"{statement} as final_matching_event")] if statement else []

    def _get_matching_events(self, max_steps: int) -> list[ast.Expr]:
        if (
            hasattr(self.context, "actorsQuery")
            and self.context.actorsQuery is not None
            and self.context.actorsQuery.includeRecordings
        ):
            events = []
            for i in range(0, max_steps):
                event_fields = ["latest", *self.extra_event_fields_and_properties]
                event_fields_with_step = ", ".join([f"{field}_{i}" for field in event_fields])
                event_clause = f"({event_fields_with_step}) AS step_{i}_matching_event"
                events.append(parse_expr(event_clause))

            return [*events, *self._get_final_matching_event(max_steps)]
        return []

    def _get_matching_event_arrays(self, max_steps: int) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []
        if (
            hasattr(self.context, "actorsQuery")
            and self.context.actorsQuery is not None
            and self.context.actorsQuery.includeRecordings
        ):
            for i in range(0, max_steps):
                exprs.append(parse_expr(f"groupArray(10)(step_{i}_matching_event) AS step_{i}_matching_events"))
            exprs.append(parse_expr(f"groupArray(10)(final_matching_event) AS final_matching_events"))
        return exprs

    def _get_step_time_avgs(self, max_steps: int, inner_query: bool = False) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []

        for i in range(1, max_steps):
            exprs.append(
                parse_expr(f"avg(step_{i}_conversion_time) as step_{i}_average_conversion_time_inner")
                if inner_query
                else parse_expr(f"avg(step_{i}_average_conversion_time_inner) as step_{i}_average_conversion_time")
            )

        return exprs

    def _get_step_time_median(self, max_steps: int, inner_query: bool = False) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []

        for i in range(1, max_steps):
            exprs.append(
                parse_expr(f"median(step_{i}_conversion_time) as step_{i}_median_conversion_time_inner")
                if inner_query
                else parse_expr(f"median(step_{i}_median_conversion_time_inner) as step_{i}_median_conversion_time")
            )

        return exprs

    def _get_step_time_array(self, max_steps: int) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []

        for i in range(1, max_steps):
            exprs.append(parse_expr(f"groupArray(step_{i}_conversion_time) as step_{i}_conversion_time_array"))

        return exprs

    def _get_step_time_array_avgs(self, max_steps: int) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []

        for i in range(1, max_steps):
            exprs.append(
                parse_expr(
                    f"if(isNaN(avgArray(step_{i}_conversion_time_array) as inter_{i}_conversion), NULL, inter_{i}_conversion) as step_{i}_average_conversion_time"
                )
            )

        return exprs

    def _get_step_time_array_median(self, max_steps: int) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []

        for i in range(1, max_steps):
            exprs.append(
                parse_expr(
                    f"if(isNaN(medianArray(step_{i}_conversion_time_array) as inter_{i}_median), NULL, inter_{i}_median) as step_{i}_median_conversion_time"
                )
            )

        return exprs

    def _get_timestamp_selects(self) -> tuple[list[ast.Expr], list[ast.Expr]]:
        """
        Returns timestamp selectors for the target step and optionally the preceding step.
        In the former case, always returns the timestamp for the first and last step as well.
        """
        target_step = self._absolute_actors_step

        if target_step is None:
            return [], []

        final_step = self.context.max_steps - 1
        first_step = 0

        if self.context.includePrecedingTimestamp:
            if target_step == 0:
                raise ValueError("Cannot request preceding step timestamp if target funnel step is the first step")

            return (
                [ast.Field(chain=[f"latest_{target_step}"]), ast.Field(chain=[f"latest_{target_step - 1}"])],
                [
                    parse_expr(f"argMax(latest_{target_step}, steps) AS max_timestamp"),
                    parse_expr(f"argMax(latest_{target_step - 1}, steps) AS min_timestamp"),
                ],
            )
        elif self.context.includeTimestamp:
            return (
                [
                    ast.Field(chain=[f"latest_{target_step}"]),
                    ast.Field(chain=[f"latest_{final_step}"]),
                    ast.Field(chain=[f"latest_{first_step}"]),
                ],
                [
                    parse_expr(f"argMax(latest_{target_step}, steps) AS timestamp"),
                    parse_expr(f"argMax(latest_{final_step}, steps) AS final_timestamp"),
                    parse_expr(f"argMax(latest_{first_step}, steps) AS first_timestamp"),
                ],
            )
        else:
            return [], []

    def _get_step_times(self, max_steps: int) -> list[ast.Expr]:
        windowInterval = self.context.funnelWindowInterval
        windowIntervalUnit = funnel_window_interval_unit_to_sql(self.context.funnelWindowIntervalUnit)

        exprs: list[ast.Expr] = []

        for i in range(1, max_steps):
            exprs.append(
                parse_expr(
                    f"if(isNotNull(latest_{i}) AND latest_{i} <= toTimeZone(latest_{i-1}, 'UTC') + INTERVAL {windowInterval} {windowIntervalUnit}, dateDiff('second', latest_{i - 1}, latest_{i}), NULL) as step_{i}_conversion_time"
                ),
            )

        return exprs

    def _get_partition_cols(self, level_index: int, max_steps: int) -> list[ast.Expr]:
        query, funnelsFilter = self.context.query, self.context.funnelsFilter
        exclusions = funnelsFilter.exclusions
        series = query.series

        exprs: list[ast.Expr] = []

        for i in range(0, max_steps):
            exprs.append(ast.Field(chain=[f"step_{i}"]))

            if i < level_index:
                exprs.append(ast.Field(chain=[f"latest_{i}"]))

                for field in self.extra_event_fields_and_properties:
                    exprs.append(ast.Field(chain=[f"{field}_{i}"]))

                for exclusion_id, exclusion in enumerate(exclusions or []):
                    if cast(int, exclusion.funnelFromStep) + 1 == i:
                        exprs.append(ast.Field(chain=[f"exclusion_{exclusion_id}_latest_{exclusion.funnelFromStep}"]))

            else:
                duplicate_event = 0

                if i > 0 and (is_equal(series[i], series[i - 1]) or is_superset(series[i], series[i - 1])):
                    duplicate_event = 1

                exprs.append(
                    parse_expr(
                        f"min(latest_{i}) over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND {duplicate_event} PRECEDING) as latest_{i}"
                    )
                )

                for field in self.extra_event_fields_and_properties:
                    exprs.append(
                        parse_expr(
                            f'last_value("{field}_{i}") over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND {duplicate_event} PRECEDING) as "{field}_{i}"'
                        )
                    )

                for exclusion_id, exclusion in enumerate(exclusions or []):
                    # exclusion starting at step i follows semantics of step i+1 in the query (since we're looking for exclusions after step i)
                    if cast(int, exclusion.funnelFromStep) + 1 == i:
                        exprs.append(
                            parse_expr(
                                f"min(exclusion_{exclusion_id}_latest_{exclusion.funnelFromStep}) over (PARTITION by aggregation_target {self._get_breakdown_prop()} ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) as exclusion_{exclusion_id}_latest_{exclusion.funnelFromStep}"
                            )
                        )

        return exprs

    def _get_breakdown_prop_expr(self, group_remaining=False) -> list[ast.Expr]:
        # SEE BELOW for a string implementation of the following
        if self.context.breakdown:
            return [ast.Field(chain=["prop"])]
        else:
            return []

    def _get_breakdown_prop(self, group_remaining=False) -> str:
        # SEE ABOVE for an ast implementation of the following
        if self.context.breakdown:
            return ", prop"
        else:
            return ""

    def _query_has_array_breakdown(self) -> bool:
        breakdown, breakdownType = self.context.breakdown, self.context.breakdownType
        return breakdown is not None and not isinstance(breakdown, str) and breakdownType != "cohort"

    def _get_exclusion_condition(self) -> list[ast.Expr]:
        funnelsFilter = self.context.funnelsFilter
        windowInterval = self.context.funnelWindowInterval
        windowIntervalUnit = funnel_window_interval_unit_to_sql(self.context.funnelWindowIntervalUnit)

        if not funnelsFilter.exclusions:
            return []

        conditions: list[ast.Expr] = []

        for exclusion_id, exclusion in enumerate(funnelsFilter.exclusions):
            from_time = f"latest_{exclusion.funnelFromStep}"
            to_time = f"latest_{exclusion.funnelToStep}"
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

    def _get_sorting_condition(self, curr_index: int, max_steps: int) -> ast.Expr:
        series = self.context.query.series
        windowInterval = self.context.funnelWindowInterval
        windowIntervalUnit = funnel_window_interval_unit_to_sql(self.context.funnelWindowIntervalUnit)

        if curr_index == 1:
            return ast.Constant(value=1)

        conditions: list[ast.Expr] = []

        for i in range(1, curr_index):
            duplicate_event = is_equal(series[i], series[i - 1]) or is_superset(series[i], series[i - 1])

            conditions.append(parse_expr(f"latest_{i - 1} {'<' if duplicate_event else '<='} latest_{i}"))
            conditions.append(
                parse_expr(
                    f"latest_{i} <= toTimeZone(latest_0, 'UTC') + INTERVAL {windowInterval} {windowIntervalUnit}"
                )
            )

        return ast.Call(
            name="if",
            args=[
                ast.And(exprs=conditions),
                ast.Constant(value=curr_index),
                self._get_sorting_condition(curr_index - 1, max_steps),
            ],
        )

    def _get_person_and_group_properties(self, aggregate: bool = False) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []

        for prop in self.context.includeProperties:
            exprs.append(parse_expr(f"any({prop}) as {prop}") if aggregate else parse_expr(prop))

        return exprs

    def _get_step_counts_query(self, outer_select: list[ast.Expr], inner_select: list[ast.Expr]) -> ast.SelectQuery:
        max_steps, funnel_viz_type = self.context.max_steps, self.context.funnelsFilter.funnelVizType
        breakdown_exprs = self._get_breakdown_prop_expr()
        inner_timestamps, outer_timestamps = self._get_timestamp_selects()
        person_and_group_properties = self._get_person_and_group_properties(aggregate=True)
        breakdown, breakdownType = self.context.breakdown, self.context.breakdownType

        group_by_columns: list[ast.Expr] = [
            ast.Field(chain=["aggregation_target"]),
            ast.Field(chain=["steps"]),
            *breakdown_exprs,
        ]

        outer_select = [
            *outer_select,
            *group_by_columns,
            *breakdown_exprs,
            *outer_timestamps,
            *person_and_group_properties,
        ]
        if (
            funnel_viz_type != FunnelVizType.TIME_TO_CONVERT
            and breakdown
            and breakdownType
            in [
                BreakdownType.PERSON,
                BreakdownType.EVENT,
                BreakdownType.GROUP,
            ]
        ):
            time_fields = [
                parse_expr(f"min(step_{i}_conversion_time) as step_{i}_conversion_time") for i in range(1, max_steps)
            ]
            outer_select.extend(time_fields)
        else:
            outer_select = [
                *outer_select,
                *self._get_step_time_avgs(max_steps, inner_query=True),
                *self._get_step_time_median(max_steps, inner_query=True),
            ]
        max_steps_expr = parse_expr(
            f"max(steps) over (PARTITION BY aggregation_target {self._get_breakdown_prop()}) as max_steps"
        )

        inner_select = [
            *inner_select,
            *group_by_columns,
            max_steps_expr,
            *self._get_step_time_names(max_steps),
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
            having=parse_expr("steps = max(max_steps)"),
        )

    def actor_query(
        self,
        extra_fields: Optional[list[str]] = None,
    ) -> ast.SelectQuery:
        select: list[ast.Expr] = [
            ast.Alias(alias="actor_id", expr=ast.Field(chain=["aggregation_target"])),
            *self._get_funnel_person_step_events(),
            *self._get_timestamp_outer_select(),
            *([ast.Field(chain=[field]) for field in extra_fields or []]),
        ]
        select_from = ast.JoinExpr(table=self.get_step_counts_query())
        where = self._get_funnel_person_step_condition()
        order_by = [ast.OrderExpr(expr=ast.Field(chain=["aggregation_target"]))]

        return ast.SelectQuery(
            select=select,
            select_from=select_from,
            order_by=order_by,
            where=where,
        )
