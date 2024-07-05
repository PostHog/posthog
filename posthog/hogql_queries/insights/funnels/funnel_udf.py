from datetime import datetime
from itertools import groupby
from typing import Any, Optional
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql_queries.insights.funnels.base import FunnelBase
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.utils import get_funnel_order_class
from posthog.hogql_queries.insights.utils.utils import get_start_of_interval_hogql
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.cohort.cohort import Cohort
from posthog.queries.util import correct_result_for_sampling, get_earliest_timestamp, get_interval_func_ch

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HUMAN_READABLE_TIMESTAMP_FORMAT = "%-d-%b-%Y"


class FunnelUDF(FunnelBase):
    def get_query(self) -> ast.SelectQuery:
        return parse_select("""
            SELECT
                e.person_id AS aggregation_target,
                arrayReverseSort((x) -> x.1, groupArray(tuple(e.event, e.timestamp))) as events
                --groupArrayIf(e.event, equals(e.event, 'welcome_screen_create_account_button')) as step_0,
                --groupArrayIf(e.event, equals(e.event, 'reg_patient_info_view')) as step_1
            FROM
                events AS e
            WHERE
                and(
                    equals(e.team_id, 19486), 
                    and(
                        and(
                            greaterOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2024-05-29 00:00:00.000000', 6, 'UTC')), 
                            lessOrEquals(toTimeZone(e.timestamp, 'UTC'), toDateTime64('2024-06-28 23:59:59.999999', 6, 'UTC'))
                        ),
                        in(e.event, tuple('reg_patient_info_view', 'welcome_screen_create_account_button')), true)
                    )
            GROUP BY
                 aggregation_target
            SETTINGS allow_experimental_analyzer=1
        """)
