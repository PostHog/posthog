from datetime import datetime
from itertools import groupby
from typing import Any, Optional
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
from posthog.schema import BreakdownType
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
        inner_event_query = self._get_inner_event_query(entity_name='events')

        # stores the steps as an array of integers from 1 to max_steps
        # so if the event could be step_0, step_1 or step_4, it looks like [1,2,0,0,5]
        steps = ",".join([f"{i + 1} * step_{i}" for i in range(self.context.max_steps)])

        inner_select = parse_select(f"""
            SELECT 
                aggregate_funnel(
                    {self.context.max_steps}, 
                    {self.conversion_window_limit()},
                    '{self.context.breakdownAttributionType}',
                    arraySort(t -> t.1, groupArray(tuple(toFloat(timestamp), {"prop[1]" if self.context.breakdown else "''"}, arrayFilter((x) -> x != 0, [{steps}]))))
                ) as af_tuple,
                af_tuple.1 as af,
                af_tuple.2 as breakdown
            FROM {{inner_event_query}}
            GROUP BY aggregation_target
        """, {'inner_event_query': inner_event_query})

        step_results = ",".join([f"countIf(ifNull(equals(af, {i}), 0)) AS step_{i+1}" for i in range(self.context.max_steps)])

        mean_conversion_times = ",".join([f"0 AS step_{i+1}_average_conversion_time" for i in range(self.context.max_steps)])
        median_conversion_times = ",".join([f"0 AS step_{i+1}_median_conversion_time" for i in range(self.context.max_steps)])

        s = parse_select(f"""
            SELECT
                {step_results},
                {mean_conversion_times},
                {median_conversion_times}
            FROM 
                {{inner_select}}
        """, {'inner_select': inner_select})

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




