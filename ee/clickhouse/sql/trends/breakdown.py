BREAKDOWN_QUERY_SQL = """
SELECT groupArray(day_start) as date, groupArray(count) as data, breakdown_value FROM (
    SELECT SUM(total) as count, day_start, breakdown_value FROM (
        SELECT * FROM (
            SELECT
            toUInt16(0) AS total,
            {interval}(toDateTime(%(date_to)s) - number * %(seconds_in_interval)s) as day_start,
            breakdown_value from numbers(%(num_intervals)s) as main
            CROSS JOIN
                (
                    SELECT breakdown_value
                    FROM (
                        SELECT %(values)s as breakdown_value
                    ) ARRAY JOIN breakdown_value
                ) as sec
            ORDER BY breakdown_value, day_start
            UNION ALL
            {inner_sql}
        )
    )
    GROUP BY day_start, breakdown_value
    ORDER BY breakdown_value, day_start
) GROUP BY breakdown_value
"""

BREAKDOWN_INNER_SQL = """
SELECT
    {aggregate_operation} as total,
    toDateTime({interval_annotation}(timestamp), 'UTC') as day_start,
    {breakdown_value} as breakdown_value
FROM
events e {event_join} {breakdown_filter}
GROUP BY day_start, breakdown_value
"""

BREAKDOWN_ACTIVE_USER_INNER_SQL = """
SELECT counts as total, timestamp as day_start, breakdown_value
FROM (
    SELECT d.timestamp, COUNT(DISTINCT person_id) counts, breakdown_value FROM (
        SELECT toStartOfDay(timestamp) as timestamp FROM events e WHERE team_id = %(team_id)s {parsed_date_from_prev_range} {parsed_date_to} GROUP BY timestamp
    ) d
    CROSS JOIN (
        SELECT toStartOfDay(timestamp) as timestamp, person_id, {breakdown_value} as breakdown_value
        FROM events e
        INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) as pdi
        ON e.distinct_id = pdi.distinct_id
        {event_join}
        {conditions}
        GROUP BY timestamp, person_id, breakdown_value
    ) e
    WHERE e.timestamp <= d.timestamp AND e.timestamp > d.timestamp - INTERVAL {prev_interval}
    GROUP BY d.timestamp, breakdown_value
    ORDER BY d.timestamp
) WHERE 11111 = 11111 {parsed_date_from} {parsed_date_to}
"""


BREAKDOWN_AGGREGATE_QUERY_SQL = """
SELECT {aggregate_operation} AS total, {breakdown_value} AS breakdown_value
FROM
events e {event_join} {breakdown_filter}
GROUP BY breakdown_value
"""

BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL = """
WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from_prev_range} {parsed_date_to} {actions_query}
"""

BREAKDOWN_PROP_JOIN_SQL = """
WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to}
  AND {breakdown_value_expr} in (%(values)s)
  {actions_query}
"""

BREAKDOWN_COHORT_JOIN_SQL = """
INNER JOIN (
    {cohort_queries}
) ep
ON e.distinct_id = ep.distinct_id where team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to} {actions_query}
"""
