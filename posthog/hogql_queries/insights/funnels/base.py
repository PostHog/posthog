import uuid
import itertools
from abc import ABC
from functools import cached_property
from typing import Any, Optional, Union

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    BreakdownType,
    DataWarehouseNode,
    EventsNode,
    FunnelTimeToConvertResults,
    FunnelVizType,
    StepOrderValue,
)

from posthog.hogql import ast
from posthog.hogql.constants import get_breakdown_limit_for_context
from posthog.hogql.parser import parse_expr, parse_select

from posthog.clickhouse.materialized_columns import ColumnName
from posthog.hogql_queries.insights.funnels.funnel_event_query import FunnelEventQuery
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.utils import funnel_window_interval_unit_to_sql
from posthog.hogql_queries.insights.utils.entities import is_equal, is_superset
from posthog.models.action.action import Action
from posthog.models.cohort.cohort import Cohort
from posthog.models.property.property import PropertyName
from posthog.queries.breakdown_props import ALL_USERS_COHORT_ID, get_breakdown_cohort_name
from posthog.queries.util import correct_result_for_sampling

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
    def event_array_filter(self, timestamp_index: int, prop_val_index: int, steps_index: int):
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
        if isinstance(step, EventsNode):
            step_type = "events"
        elif isinstance(step, ActionsNode):
            step_type = "actions"
        elif isinstance(step, DataWarehouseNode):
            step_type = "data_warehouse"
        else:
            raise TypeError(f"Unsupported step type {type(step)}")

        if self.context.funnelsFilter.funnelOrderType == StepOrderValue.UNORDERED:
            return {
                "action_id": None,
                "name": f"Completed {index + 1} step{'s' if index != 0 else ''}",
                "custom_name": None,
                "order": index,
                "people": people if people else [],
                "count": correct_result_for_sampling(count, sampling_factor),
                "type": step_type,
            }

        action_id: Optional[str | int]
        if isinstance(step, EventsNode):
            name = step.event
            action_id = step.event
        elif isinstance(step, DataWarehouseNode):
            name = f"{step.table_name}.{step.distinct_id_field}"
            action_id = None
        else:
            action = Action.objects.get(pk=step.id, team__project_id=self.context.team.project_id)
            name = action.name
            action_id = step.id

        return {
            "action_id": action_id,
            "name": name,
            "custom_name": step.custom_name,
            "order": index,
            "people": people if people else [],
            "count": correct_result_for_sampling(count, sampling_factor),
            "type": step_type,
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

    # This version of the inner event query modifies how exclusions are returned to
    # make them behave more like steps. It returns a boolean "exclusion_{0..n}" for each event
    def _get_inner_event_query(
        self,
        skip_entity_filter=False,
        skip_step_filter=False,
    ) -> ast.SelectQuery:
        breakdown, breakdownType = (
            self.context.breakdown,
            self.context.breakdownType,
        )

        funnel_events_query = FunnelEventQuery(
            context=self.context,
            extra_event_fields_and_properties=self.extra_event_fields_and_properties,
        ).to_query(
            skip_entity_filter=skip_entity_filter,
            skip_step_filter=skip_step_filter,
        )

        # TODO: cohort breakdowns are not supported for data warehouse / mixed funnels at the moment
        if breakdown and breakdownType == BreakdownType.COHORT:
            assert funnel_events_query.select_from is not None
            funnel_events_query.select_from.next_join = self._get_cohort_breakdown_join()

        return funnel_events_query

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
            # TODO: cohort breakdowns are not supported for data warehouse / mixed funnels at the moment
            all_query = FunnelEventQuery(context=self.context).to_query(skip_step_filter=True)
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

    def get_breakdown_limit(self):
        return self.context.breakdownFilter.breakdown_limit or get_breakdown_limit_for_context(
            self.context.limit_context
        )

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

    def _get_step_time_names(self, max_steps: int) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []

        for i in range(1, max_steps):
            exprs.append(parse_expr(f"step_{i}_conversion_time"))

        return exprs

    def _get_final_matching_event(self, max_steps: int) -> list[ast.Expr]:
        statement = None
        for i in range(max_steps - 1, -1, -1):
            if i == max_steps - 1:
                statement = f"if(isNull(latest_{i}),step_{i - 1}_matching_event,step_{i}_matching_event)"
            elif i == 0:
                statement = f"if(isNull(latest_0),(null,null,null,null),{statement})"
            else:
                statement = f"if(isNull(latest_{i}),step_{i - 1}_matching_event,{statement})"
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

    def _get_breakdown_prop_expr(self) -> list[ast.Expr]:
        # SEE BELOW for a string implementation of the following
        if self.context.breakdown:
            return [ast.Field(chain=["prop"])]
        else:
            return []

    def _get_breakdown_prop(self) -> str:
        # SEE ABOVE for an ast implementation of the following
        if self.context.breakdown:
            return ", prop"
        else:
            return ""

    def _query_has_array_breakdown(self) -> bool:
        breakdown, breakdownType = self.context.breakdown, self.context.breakdownType
        return breakdown is not None and not isinstance(breakdown, str) and breakdownType != "cohort"

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
