from typing import Any, Callable, Dict, List, Tuple

from ee.clickhouse.queries.trends.trend_event_query import TrendsEventQuery
from ee.clickhouse.queries.trends.util import parse_response, process_math
from ee.clickhouse.queries.util import (
    format_ch_timestamp,
    get_earliest_timestamp,
    get_interval_func_ch,
    get_trunc_func_ch,
)
from posthog.constants import MONTHLY_ACTIVE, TRENDS_DISPLAY_BY_VALUE, WEEKLY_ACTIVE
from posthog.models.entity import Entity
from posthog.models.filters import Filter


class ClickhouseTrendsTotalVolume:
    def _total_volume_query(self, entity: Entity, filter: Filter, team_id: int) -> Tuple[str, Dict, Callable]:
        trunc_func = get_trunc_func_ch(filter.interval)
        interval_func = get_interval_func_ch(filter.interval)
        aggregate_operation, join_condition, math_params = process_math(entity)

        trend_event_query = TrendsEventQuery(
            filter=filter,
            entity=entity,
            team_id=team_id,
            should_join_distinct_ids=True
            if join_condition != "" or entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]
            else False,
        )
        event_query, event_query_params = trend_event_query.get_query()

        content_sql_params = {
            "aggregate_operation": aggregate_operation,
            "timestamp": "e.timestamp",
            "interval": trunc_func,
            "interval_func": interval_func,
        }
        params: Dict = {"team_id": team_id}
        params = {**params, **math_params, **event_query_params}

        if entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
            final_query = ACTIVE_USER_SQL.format(
                event_query=event_query,
                **content_sql_params,
                parsed_date_to=trend_event_query.parsed_date_to,
                parsed_date_from=trend_event_query.parsed_date_from,
                **trend_event_query.active_user_params
            )
        else:
            final_query = VOLUME_SQL.format(event_query=event_query, **content_sql_params)

        params["date_from"] = format_ch_timestamp(filter.date_from or get_earliest_timestamp(team_id), filter)
        params["date_to"] = format_ch_timestamp(filter.date_to, filter)
        params["interval"] = filter.interval
        return final_query, params, self._parse_total_volume_result(filter)

    def _parse_total_volume_result(self, filter: Filter) -> Callable:
        def _parse(result: List) -> List:
            # NOTE: there's some implicit coupling here:
            #
            #        1. the ordering of the fields we get back, (date, value)
            #        2. that the last row is always the `WITH TOTALS` result
            #
            #  TODO: remove coupling

            #  The last row relates to the `WITH TOTALS` from the clickhouse query
            values_without_totals, (_, aggregated_value) = result[:-1], result[-1]

            # Separate dates and values, as desired for the REST API response
            dates, values = zip(*sorted(values_without_totals))

            parsed_result = parse_response([dates, values], filter)

            # NOTE: to maintain backwards compatability here from previous behaviour, we exclude the
            #        `aggregated_value` for some filter.display.
            # TODO: verify if updating to always including `aggregated_value` would break anything. It
            #       would be simpler to not have to have this special casing in here.
            if filter.display in TRENDS_DISPLAY_BY_VALUE:
                parsed_result["aggregated_value"] = aggregated_value

            return [parsed_result]

        return _parse


ZERO_FILL_TEMPLATE = """
SELECT 
    interval.start AS interval_start,

    -- For where we don't have an aggregate value, we zero fill
    COALESCE(aggregate.value, 0) AS value

FROM (
    -- Creates zero values for all date axis ticks for the given date_from, date_to range
    -- NOTE: I had a look at using the `WITH FILL` modifier for `ORDER BY` but it didn't work
    --       well for week and month intervals. Looks like you'd have to do some other wrangling
    --       to get it to work as expected:
    --
    --           https://stackoverflow.com/questions/66092272/clickhouse-order-by-with-fill-month-interval
    --

    SELECT {{interval}}(
        toDateTime(%(date_to)s) - {{interval_func}}(number)
    ) AS start

    FROM numbers(
        dateDiff(
            %(interval)s, 
            {{interval}}(toDateTime(%(date_from)s)), 
            {{interval}}(toDateTime(%(date_to)s))
        ) + 1
    )
) interval

-- left join so we end up with values for all intervals, even if we don't have an aggregate
LEFT JOIN (
        
    {aggregate_query}

) aggregate ON aggregate.interval_start = interval_start
"""


def zero_fill(aggregate_query: str) -> str:
    """
    WWraps the provided query with a JOIN that will fill in any missing interval
    rows with zeros.

    NOTE: it's a little messy to be handling these query string manipulations. At the 
          moment there are hidden dependencies on the params that are passed in and the 
          referenced select and filter fields between string segments.

          For instance, we're treating these as if they are just string, but they are 
          templates with a specific format params structure.

    TODO: create a better abstraction for this. Perhaps an expressive enough data structure 
          for describing a query in the abstract, and a query executor/renderer.
    """
    return ZERO_FILL_TEMPLATE.format(aggregate_query=aggregate_query)


VOLUME_SQL = zero_fill(
    aggregate_query="""
    -- Selects all events from the `event_query` and aggregates them with
    -- `aggregation_operation`, grouped by bucket sizes specified by `interval`
    -- 
    -- NOTE: we're building a big subquery here of all matching events. This is going to 
    --       be creating a big temporary table and hurting performance.
    --
    -- TODO: #6107 #6106 remove the events subquery here and filter and aggregate in one query instead, 
    --       to avoid large temporary tables

    SELECT 
        toDateTime({interval}(timestamp), 'UTC') as interval_start,
        {aggregate_operation} as value
    FROM ({event_query}) 
    GROUP BY {interval}(timestamp)
        -- We use TOTALS to get the total aggregate value, ignoring interval buckets
        WITH TOTALS
"""
)


ACTIVE_USER_SQL = zero_fill(
    aggregate_query="""
    SELECT 
        d.timestamp as interval_start, 
        COUNT(DISTINCT person_id) as value
    FROM (
        SELECT toStartOfDay(timestamp) as timestamp 
        FROM events 
        WHERE team_id = %(team_id)s {parsed_date_from_prev_range} {parsed_date_to} 
        GROUP BY timestamp 
    ) d
    CROSS JOIN (
        SELECT toStartOfDay(timestamp) as timestamp, person_id 
        FROM ({event_query}) events 
        WHERE 1 = 1 {parsed_date_from_prev_range} {parsed_date_to} 
        GROUP BY timestamp, person_id
    ) e 
    WHERE 
            e.timestamp <= d.timestamp
        AND e.timestamp > d.timestamp - INTERVAL {prev_interval}
    GROUP BY d.timestamp
        WITH TOTALS
    ORDER BY d.timestamp
"""
)
