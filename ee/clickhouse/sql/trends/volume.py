VOLUME_SQL = """
SELECT {aggregate_operation} as data, {interval}(toDateTime(timestamp), {start_of_week_fix} %(timezone)s) as date FROM ({event_query}) GROUP BY date
"""

VOLUME_TOTAL_AGGREGATE_SQL = """
SELECT {aggregate_operation} as data FROM ({event_query}) events
"""

ACTIVE_USER_SQL = """
SELECT counts as total, timestamp as day_start FROM (
    SELECT d.timestamp, COUNT(DISTINCT {aggregator}) counts FROM (
        SELECT toStartOfDay(toDateTime(timestamp, %(timezone)s)) as timestamp FROM events WHERE team_id = %(team_id)s {parsed_date_from_prev_range} {parsed_date_to} GROUP BY timestamp
    ) d
    CROSS JOIN (
        SELECT toStartOfDay(toDateTime(timestamp, %(timezone)s)) as timestamp, {aggregator} FROM ({event_query}) events WHERE 1 = 1 {parsed_date_from_prev_range} {parsed_date_to} GROUP BY timestamp, {aggregator}
    ) e WHERE e.timestamp <= d.timestamp AND e.timestamp > d.timestamp - INTERVAL {prev_interval}
    GROUP BY d.timestamp
    ORDER BY d.timestamp
) WHERE 1 = 1 {parsed_date_from} {parsed_date_to}
"""

AGGREGATE_SQL = """
SELECT groupArray(day_start) as date, groupArray({aggregate}) as data FROM (
    SELECT {smoothing_operation} AS count, day_start
    from (
        {null_sql}
        UNION ALL
        {content_sql}
    )
    group by day_start
    order by day_start
    SETTINGS allow_experimental_window_functions = 1
)
SETTINGS timeout_before_checking_execution_speed = 60
"""

CUMULATIVE_SQL = """
SELECT person_id, min(timestamp) as timestamp
FROM ({event_query}) GROUP BY person_id
"""
