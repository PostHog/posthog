from typing import cast, Optional

from posthog.hogql import ast
from posthog.hogql.parser import parse_select, parse_expr
from posthog.hogql_queries.insights.funnels.base import FunnelBase
from posthog.schema import BreakdownType, BreakdownAttributionType
from posthog.utils import DATERANGE_MAP

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HUMAN_READABLE_TIMESTAMP_FORMAT = "%-d-%b-%Y"


class FunnelUDF(FunnelBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # In base, these fields only get added if you're running an actors query
        if "uuid" not in self._extra_event_fields:
            self._extra_event_fields.append("uuid")
        for property in ("$session_id", "$window_id"):
            if property not in self._extra_event_properties:
                self._extra_event_properties.append(property)

    def conversion_window_limit(self) -> int:
        return int(
            self.context.funnelWindowInterval * DATERANGE_MAP[self.context.funnelWindowIntervalUnit].total_seconds()
        )

    def matched_event_arrays_selects(self):
        # We use matched events to get timestamps for the funnel as well as recordings
        if self._include_matched_events() or self.context.includePrecedingTimestamp or self.context.includeTimestamp:
            return """
            af_tuple.4 as matched_event_uuids_array_array,
            groupArray(tuple(timestamp, uuid, $session_id, $window_id)) as user_events,
            mapFromArrays(arrayMap(x -> x.2, user_events), user_events) as user_events_map,
            arrayMap(matched_event_uuids_array -> arrayMap(event_uuid -> user_events_map[event_uuid], arrayDistinct(matched_event_uuids_array)), matched_event_uuids_array_array) as matched_events_array,
            """
        return ""

    def udf_event_array_filter(self):
        return self._udf_event_array_filter(1, 3, 4)

    # This is the function that calls the UDF
    # This is used by both the query itself and the actors query
    def _inner_aggregation_query(self):
        if self.context.funnelsFilter.funnelOrderType == "strict":
            inner_event_query = self._get_inner_event_query_for_udf(
                entity_name="events", skip_step_filter=True, skip_entity_filter=True
            )
        else:
            inner_event_query = self._get_inner_event_query_for_udf(entity_name="events")

        default_breakdown_selector = "[]" if self._query_has_array_breakdown() else "''"

        # stores the steps as an array of integers from 1 to max_steps
        # so if the event could be step_0, step_1 or step_4, it looks like [1,2,0,0,5]

        # Each event is going to be a set of steps or it's going to be a set of exclusions. It can't be both.
        steps = ",".join([f"{i + 1} * step_{i}" for i in range(self.context.max_steps)])

        # this will error if they put in a bad exclusion
        exclusions = ""
        if getattr(self.context.funnelsFilter, "exclusions", None):
            exclusions = "".join([f",-{i + 1} * exclusion_{i}" for i in range(1, self.context.max_steps)])

        if self.context.breakdownType == BreakdownType.COHORT:
            fn = "aggregate_funnel_cohort"
            breakdown_prop = ", prop"
        elif self._query_has_array_breakdown():
            fn = "aggregate_funnel_array"
            breakdown_prop = ""
        else:
            fn = "aggregate_funnel"
            breakdown_prop = ""

        prop_selector = "prop" if self.context.breakdown else default_breakdown_selector
        prop_vals = "groupUniqArray(prop)" if self.context.breakdown else f"[{default_breakdown_selector}]"

        breakdown_attribution_string = f"{self.context.breakdownAttributionType}{f'_{self.context.funnelsFilter.breakdownAttributionValue}' if self.context.breakdownAttributionType == BreakdownAttributionType.STEP else ''}"

        inner_select = parse_select(
            f"""
            SELECT
                arraySort(t -> t.1, groupArray(tuple(
                    toFloat(timestamp),
                    uuid,
                    {prop_selector},
                    arrayFilter((x) -> x != 0, [{steps}{exclusions}])
                ))) as events_array,
                arrayJoin({fn}(
                    {self.context.max_steps},
                    {self.conversion_window_limit()},
                    '{breakdown_attribution_string}',
                    '{self.context.funnelsFilter.funnelOrderType}',
                    {prop_vals},
                    {self.udf_event_array_filter()}
                )) as af_tuple,
                af_tuple.1 as step_reached,
                af_tuple.1 + 1 as steps, -- Backward compatibility
                af_tuple.2 as breakdown,
                af_tuple.3 as timings,
                {self.matched_event_arrays_selects()}
                aggregation_target
            FROM {{inner_event_query}}
            GROUP BY aggregation_target{breakdown_prop}
            HAVING step_reached >= 0
        """,
            {"inner_event_query": inner_event_query},
        )
        return inner_select

    def get_query(self) -> ast.SelectQuery:
        inner_select = self._inner_aggregation_query()

        step_results = ",".join(
            [f"countIf(ifNull(equals(step_reached, {i}), 0)) AS step_{i+1}" for i in range(self.context.max_steps)]
        )
        step_results2 = ",".join([f"sum(step_{i+1}) AS step_{i+1}" for i in range(self.context.max_steps)])

        conversion_time_arrays = ",".join(
            [
                f"groupArrayIf(timings[{i}], timings[{i}] > 0) AS step_{i}_conversion_times"
                for i in range(1, self.context.max_steps)
            ]
        )

        order_by = ",".join([f"step_{i+1} DESC" for i in reversed(range(self.context.max_steps))])

        other_aggregation = "['Other']" if self._query_has_array_breakdown() else "'Other'"

        use_breakdown_limit = self.context.breakdown and self.context.breakdownType in [
            BreakdownType.PERSON,
            BreakdownType.EVENT,
            BreakdownType.GROUP,
        ]

        final_prop = (
            f"if(row_number < {self.get_breakdown_limit()}, breakdown, {other_aggregation})"
            if use_breakdown_limit
            else "breakdown"
        )

        s = parse_select(
            f"""
            SELECT
                {step_results},
                {conversion_time_arrays},
                rowNumberInBlock() as row_number,
                {final_prop} as final_prop
            FROM
                {{inner_select}}
            GROUP BY breakdown
            ORDER BY {order_by}
        """,
            {"inner_select": inner_select},
        )

        mean_conversion_times = ",".join(
            [
                f"arrayMap(x -> if(isNaN(x), NULL, x), [avgArray(step_{i}_conversion_times)])[1] AS step_{i}_average_conversion_time"
                for i in range(1, self.context.max_steps)
            ]
        )
        median_conversion_times = ",".join(
            [
                f"arrayMap(x -> if(isNaN(x), NULL, x), [medianArray(step_{i}_conversion_times)])[1] AS step_{i}_median_conversion_time"
                for i in range(1, self.context.max_steps)
            ]
        )

        # Weird: unless you reference row_number in this outer block, it doesn't work correctly
        s = parse_select(
            f"""
            SELECT
                {step_results2},
                {mean_conversion_times},
                {median_conversion_times},
                groupArray(row_number) as row_number,
                final_prop
            FROM
                {{s}}
            GROUP BY final_prop
        """,
            {"s": s},
        )

        return cast(ast.SelectQuery, s)

    def _get_funnel_person_step_condition(self) -> ast.Expr:
        actorsQuery, breakdownType = (
            self.context.actorsQuery,
            self.context.breakdownType,
        )
        assert actorsQuery is not None

        funnelStep = actorsQuery.funnelStep
        funnelCustomSteps = actorsQuery.funnelCustomSteps
        funnelStepBreakdown = actorsQuery.funnelStepBreakdown

        conditions: list[ast.Expr] = []

        if funnelCustomSteps:
            # this is an adjustment for how UDF funnels represent steps
            funnelCustomSteps = [x - 1 for x in funnelCustomSteps]
            conditions.append(parse_expr(f"step_reached IN {funnelCustomSteps}"))
        elif funnelStep is not None:
            if funnelStep >= 0:
                conditions.append(parse_expr(f"step_reached >= {funnelStep - 1}"))
            else:
                conditions.append(parse_expr(f"step_reached = {-funnelStep - 2}"))
        else:
            raise ValueError("Missing both funnelStep and funnelCustomSteps")

        if funnelStepBreakdown is not None:
            if isinstance(funnelStepBreakdown, int) and breakdownType != "cohort":
                funnelStepBreakdown = str(funnelStepBreakdown)

            conditions.append(
                parse_expr(
                    "arrayFlatten(array(breakdown)) = arrayFlatten(array({funnelStepBreakdown}))",
                    {"funnelStepBreakdown": ast.Constant(value=funnelStepBreakdown)},
                )
            )

        return ast.And(exprs=conditions)

    def _get_funnel_person_step_events(self) -> list[ast.Expr]:
        if (
            hasattr(self.context, "actorsQuery")
            and self.context.actorsQuery is not None
            and self.context.actorsQuery.includeRecordings
        ):
            if self.context.includeFinalMatchingEvents:
                # Always returns the user's final step of the funnel, 1 indexed
                return [parse_expr("matched_events_array[step_reached + 1] as matching_events")]

            absolute_actors_step = self._absolute_actors_step
            if absolute_actors_step is None:
                raise ValueError("Missing funnelStep actors query property")
            return [parse_expr(f"matched_events_array[{absolute_actors_step + 1}] as matching_events")]
        return []

    def _get_timestamp_outer_select(self) -> list[ast.Expr]:
        """
        Returns timestamp selectors for the target step and optionally the preceding step.
        In the former case, always returns the timestamp for the first and last step as well.
        """
        target_step = self._absolute_actors_step

        if target_step is None:
            return []

        # We pull timestamps from matched_events_array and SQL arrays are 1-indexed
        target_step += 1

        final_step = self.context.max_steps
        first_step = 1

        if self.context.includePrecedingTimestamp:
            if target_step == 0:
                raise ValueError("Cannot request preceding step timestamp if target funnel step is the first step")

            return [
                parse_expr(f"matched_events_array[{target_step}][1].1 AS max_timestamp"),
                parse_expr(f"matched_events_array[{target_step - 1}][1].1 AS min_timestamp"),
            ]
        elif self.context.includeTimestamp:
            return [
                parse_expr(f"matched_events_array[{target_step}][1].1 AS timestamp"),
                # Correlation code expects null if user hasn't made it to this step
                parse_expr(f"nullIf(matched_events_array[{final_step}][1].1, 0) AS final_timestamp"),
                parse_expr(f"matched_events_array[{first_step}][1].1 as first_timestamp"),
            ]
        else:
            return []

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
        select_from = ast.JoinExpr(table=self._inner_aggregation_query())
        where = self._get_funnel_person_step_condition()
        order_by = [ast.OrderExpr(expr=ast.Field(chain=["aggregation_target"]))]

        return ast.SelectQuery(
            select=select,
            select_from=select_from,
            order_by=order_by,
            where=where,
        )
