from datetime import datetime
from itertools import groupby
from typing import Any, Optional

from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql_queries.insights.funnels.base import FunnelBase
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.utils import get_funnel_order_class
from posthog.hogql_queries.insights.utils.utils import get_start_of_interval_hogql
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.cohort.cohort import Cohort
from posthog.queries.funnels.funnel_event_query import FunnelEventQuery
from posthog.queries.util import correct_result_for_sampling, get_earliest_timestamp, get_interval_func_ch
from posthog.schema import BreakdownType, BreakdownAttributionType
from posthog.types import EntityNode, ExclusionEntityNode
from posthog.utils import DATERANGE_MAP

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HUMAN_READABLE_TIMESTAMP_FORMAT = "%-d-%b-%Y"


class FunnelUDF(FunnelBase):

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

    def conversion_window_limit(self) -> int:
        return int(self.context.funnelWindowInterval * DATERANGE_MAP[self.context.funnelWindowIntervalUnit].total_seconds())


    def get_query(self) -> ast.SelectQuery:
        inner_event_query = self._get_new_inner_event_query(entity_name='events')

        default_breakdown_selector = "[]" if self._query_has_array_breakdown() else "''"

        # stores the steps as an array of integers from 1 to max_steps
        # so if the event could be step_0, step_1 or step_4, it looks like [1,2,0,0,5]

        # Exclusions should be stored as a range (start, end) and if they occur, we need to clear
        # progress at those
        steps = ",".join([f"{i + 1} * step_{i}" for i in range(self.context.max_steps)])

        fn = 'aggregate_funnel_array' if self._query_has_array_breakdown() else 'aggregate_funnel'

        prop_selector = 'prop' if self.context.breakdown else default_breakdown_selector

        breakdown_attribution_string = f"{self.context.breakdownAttributionType}{f'_{self.context.funnelsFilter.breakdownAttributionValue}' if self.context.breakdownAttributionType == BreakdownAttributionType.STEP else ''}"

        inner_select = parse_select(f"""
            SELECT 
                {fn}(
                    {self.context.max_steps}, 
                    {self.conversion_window_limit()},
                    '{breakdown_attribution_string}',
                    arraySort(t -> t.1, groupArray(tuple(toFloat(timestamp), {prop_selector}, arrayFilter((x) -> x != 0, [{steps}]))))
                ) as af_tuple,
                af_tuple.1 as af,
                af_tuple.2 as breakdown,
                af_tuple.3 as timings
            FROM {{inner_event_query}}
            GROUP BY aggregation_target
        """, {'inner_event_query': inner_event_query})

        step_results = ",".join([f"countIf(ifNull(equals(af, {i}), 0)) AS step_{i+1}" for i in range(self.context.max_steps)])
        step_results2 = ",".join([f"sum(step_{i+1}) AS step_{i+1}" for i in range(self.context.max_steps)])

        conversion_time_arrays = ",".join([f"groupArrayIf(timings[{i}], timings[{i}] > 0) AS step_{i}_conversion_times" for i in range(1, self.context.max_steps)])

        order_by = ",".join([f"step_{i+1} DESC" for i in reversed(range(self.context.max_steps))])

        other_aggregation = "['Other']" if self._query_has_array_breakdown() else "'Other'"

        s = parse_select(f"""
            SELECT
                {step_results},
                {conversion_time_arrays},
                rowNumberInBlock() as row_number,
                if(row_number < {self.get_breakdown_limit()}, breakdown, {other_aggregation}) as final_prop
            FROM 
                {{inner_select}}
            GROUP BY breakdown
            ORDER BY {order_by}
        """, {'inner_select': inner_select})

        mean_conversion_times = ",".join([f"avgArray(step_{i}_conversion_times) AS step_{i}_average_conversion_time" for i in range(1, self.context.max_steps)])
        median_conversion_times = ",".join([f"medianArray(step_{i}_conversion_times) AS step_{i}_median_conversion_time" for i in range(1, self.context.max_steps)])

        # Weird: unless you reference row_number in this outer block, it doesn't work correctly
        s = parse_select(f"""
            SELECT
                {step_results2},
                {mean_conversion_times},
                {median_conversion_times},
                groupArray(row_number) as row_number,
                final_prop
            FROM 
                {{s}}
            GROUP BY final_prop
        """, {'s': s})

        step_results3 = ",".join([f"step_{i+1}" for i in range(self.context.max_steps)])
        mean_conversion_times3 = ",".join(
            [f"if(isNaN(step_{i}_average_conversion_time), NULL, step_{i}_average_conversion_time) as step_{i}_average_conversion_time" for i in
             range(1, self.context.max_steps)])
        median_conversion_times3 = ",".join(
            [f"if(isNaN(step_{i}_median_conversion_time), NULL, step_{i}_median_conversion_time) as step_{i}_median_conversion_time" for i in
             range(1, self.context.max_steps)])

        s = parse_select(f"""
            SELECT
                {step_results3},
                {mean_conversion_times3},
                {median_conversion_times3},
                row_number,
                final_prop
            FROM 
                {{s}}
        """, {'s': s})

        print(print_ast(s, context=HogQLContext(
            team_id=self.context.team.pk,
            enable_select_queries=True,
        ), dialect='clickhouse', pretty=True))
        return s

        """
        ┌──────────────────timestamp─┬─aggregation_target───────────────────┬─step_0─┬─latest_0─┬─step_1─┬───────────────────latest_1─┐
        │ 2024-07-01 17:34:16.659775 │ 018f3277-29bf-0000-ac28-f2272c9b7e4c │      0 │     ᴺᵁᴸᴸ │      1 │ 2024-07-01 17:34:16.659775 │
        │ 2024-07-02 04:01:29.074177 │ 018f5ef8-fd8f-0000-12c0-9805fe1e8cae │      0 │     ᴺᵁᴸᴸ │      1 │ 2024-07-02 04:01:29.074177 │
        │ 2024-07-02 00:54:11.587875 │ 018f13a4-8652-0000-2fc9-cf87e48c7f3a │      0 │     ᴺᵁᴸᴸ │      1 │ 2024-07-02 00:54:11.587875 │
        │ 2024-07-04 03:44:44.711213 │ 018eae7b-8403-0000-b04c-5769b6d5a4ed │      0 │     ᴺᵁᴸᴸ │      1 │ 2024-07-04 03:44:44.711213 │
        │ 2024-07-04 02:35:26.045570 │ 018f50dd-aea9-0000-0006-a0c7217edeb0 │      0 │     ᴺᵁᴸᴸ │      1 │ 2024-07-04 02:35:26.045570 │
        │ 2024-07-05 03:37:59.487001 │ 018e8dd6-8b39-0000-c728-5780fe187aa0 │      0 │     ᴺᵁᴸᴸ │      1 │ 2024-07-05 03:37:59.487001 │
        │ 2024-07-05 04:36:28.171171 │ 018f59e4-b122-0000-5166-a866ac2f4831 │      0 │     ᴺᵁᴸᴸ │      1 │ 2024-07-05 04:36:28.171171 │
        └────────────────────────────┴──────────────────────────────────────┴────────┴──────────┴────────┴────────────────────────────┘

        SELECT
            toTimeZone(e.timestamp, 'UTC') AS timestamp,
            e__pdi.person_id AS aggregation_target,
            if(equals(e.event, '$pageview'), 1, 0) AS step_0,
            if(ifNull(equals(step_0, 1), 0), timestamp, NULL) AS latest_0,
            if(equals(e.event, 'paid_bill'), 1, 0) AS step_1,
            if(ifNull(equals(step_1, 1), 0), timestamp, NULL) AS latest_1
        FROM
            events AS e
            INNER JOIN (SELECT
                argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id,
                person_distinct_id2.distinct_id AS distinct_id
            FROM
                person_distinct_id2
            WHERE
                equals(person_distinct_id2.team_id, 1)
            GROUP BY
                person_distinct_id2.distinct_id
            HAVING
                ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)
            SETTINGS optimize_aggregation_in_order=1) AS e__pdi ON equals(e.distinct_id, e__pdi.distinct_id)
        WHERE
            and(equals(e.team_id, 1), and(and(greaterOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2024-06-28 00:00:00.000000', 6, 'UTC')), lessOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2024-07-05 23:59:59.999999', 6, 'UTC'))), in(e.event, tuple('$pageview', 'paid_bill'))), or(ifNull(equals(step_0, 1), 0), ifNull(equals(step_1, 1), 0)))
        """
        """
        SELECT
            toTimeZone(e.timestamp, 'UTC') AS timestamp,
            e__pdi.person_id AS aggregation_target,
            if(equals(e.event, '$pageview'), 1, 0) AS step_0,
            if(ifNull(equals(step_0, 1), 0), timestamp, NULL) AS latest_0,
            if(equals(e.event, 'paid_bill'), 1, 0) AS step_1,
            if(ifNull(equals(step_1, 1), 0), timestamp, NULL) AS latest_1,
            if(equals(e.event, '$pageview'), 1, 0) AS step_2,
            if(ifNull(equals(step_2, 1), 0), timestamp, NULL) AS latest_2,
            if(equals(e.event, '$pageview'), 1, 0) AS step_3,
            if(ifNull(equals(step_3, 1), 0), timestamp, NULL) AS latest_3,
            if(equals(e.event, '$pageview'), 1, 0) AS step_4,
            if(ifNull(equals(step_4, 1), 0), timestamp, NULL) AS latest_4
        FROM
            events AS e
            INNER JOIN (SELECT
                argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id,
                person_distinct_id2.distinct_id AS distinct_id
            FROM
                person_distinct_id2
            WHERE
                equals(person_distinct_id2.team_id, 1)
            GROUP BY
                person_distinct_id2.distinct_id
            HAVING
                ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)
            SETTINGS optimize_aggregation_in_order=1) AS e__pdi ON equals(e.distinct_id, e__pdi.distinct_id)
        WHERE
            and(equals(e.team_id, 1), and(and(greaterOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2024-06-28 00:00:00.000000', 6, 'UTC')), lessOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2024-07-05 23:59:59.999999', 6, 'UTC'))), in(e.event, tuple('$pageview', 'paid_bill'))), or(ifNull(equals(step_0, 1), 0), ifNull(equals(step_1, 1), 0), ifNull(equals(step_2, 1), 0), ifNull(equals(step_3, 1), 0), ifNull(equals(step_4, 1), 0)))
        LIMIT 100 SETTINGS readonly=2, max_execution_time=600, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=2000000, max_expanded_ast_elements=2000000, max_query_size=1048576, max_bytes_before_external_group_by=23622320128, allow_experimental_analyzer=1
        """

    """
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
        all_exclusions = []
        for index, entity in enumerate(entities_to_use):
            step_cols = self._get_step_col(entity, index, entity_name)
            all_step_cols.extend(step_cols)
            all_exclusions.append([])

        for exclusion_id, excluded_entity in enumerate(funnelsFilter.exclusions or []):
            for i in range(excluded_entity.funnelFromStep + 1, excluded_entity.funnelToStep + 1):
                all_exclusions[i].append(excluded_entity)

        for index, exclusions in enumerate(all_exclusions):
            if exclusions:
                exclusion_cols = self._get_exclusions_col(exclusions, index, entity_name)
                # every exclusion entity has the form: exclusion_<id>_step_i & timestamp exclusion_<id>_latest_i
                # where i is the starting step for exclusion on that entity
                all_step_cols.extend(exclusion_cols)

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
    """



    def _get_exclusions_col(
        self,
        exclusions: list[ExclusionEntityNode],
        index: int,
        entity_name: str,
    ) -> list[ast.Expr]:
        # step prefix is used to distinguish actual steps, and exclusion steps
        # without the prefix, we get the same parameter binding for both, which borks things up
        step_cols: list[ast.Expr] = []
        conditions = [self._build_step_query(exclusion, index, entity_name, "") for exclusion in exclusions]
        step_cols.append(
            parse_expr(f"if({{condition}}, 1, 0) as exclusion_{index}", placeholders={"condition": ast.Or(exprs=conditions)})
        )
        return step_cols



