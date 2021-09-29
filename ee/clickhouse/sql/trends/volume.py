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


VOLUME_SQL = ZERO_FILL_TEMPLATE.format(
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


ACTIVE_USER_SQL = ZERO_FILL_TEMPLATE.format(
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
