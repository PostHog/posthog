BREAKDOWN_QUERY_SQL = """
SELECT groupArray(day_start) as date, groupArray(count) as data, breakdown_value FROM (
    SELECT SUM(total) as count, day_start, breakdown_value FROM (
        SELECT * FROM (
            -- Create a table with 1 row for each interval for the requested date range
            -- This acts as a method of zero filling, i.e. when there are no data points
            -- for a given interval, we'll still have a row for the group by interval with
            -- a 0 value.
            --
            -- It's essentially a cross product of graph "ticks" and breakdown values.
            --
            -- TODO: we're relying on num_intervals, seconds_int_interval etc. being passed
            --       in as a parameter. To reduce the coupling between here and the
            --       calling code, we could perform calculations for these within the query
            --       itself based on date_to/date_from. We could also pass in the intervals
            --       explicitly, although we'll be relying on the date handling between python
            --       and ClickHouse to be the same.
            --
            -- NOTE: there is the ORDER BY ... WITH FILL Expression but I'm not sure how we'd
            --       handle the edge cases:
            --
            --          https://clickhouse.com/docs/en/sql-reference/statements/select/order-by/#orderby-with-fill
            --

            SELECT
                toUInt16(0) AS total,
                ticks.day_start as day_start,
                breakdown_value

            FROM (
                -- Generates all the intervals/ticks in the date range
                -- NOTE: we build this range by including successive intervals back from the
                --       upper bound, then including the lower bound in the query also.

                SELECT
                    {interval}(
                        toDateTime(%(date_to)s, %(timezone)s) - number * %(seconds_in_interval)s
                    ) as day_start
                FROM numbers({num_intervals})
                UNION ALL
                SELECT {interval}(toDateTime(%(date_from)s, %(timezone)s)) as day_start
            ) as ticks

            -- Zero fill for all values for the specified breakdown
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
)
GROUP BY breakdown_value
ORDER BY breakdown_value
"""

BREAKDOWN_INNER_SQL = """
SELECT
    {aggregate_operation} as total,
    {interval_annotation}(timestamp, {start_of_week_fix} %(timezone)s) as day_start,
    {breakdown_value} as breakdown_value
FROM events e
{person_join}
{groups_join}
{breakdown_filter}
GROUP BY day_start, breakdown_value
"""

BREAKDOWN_CUMULATIVE_INNER_SQL = """
SELECT
    {aggregate_operation} as total,
    {interval_annotation}(timestamp, {start_of_week_fix} %(timezone)s) as day_start,
    breakdown_value
FROM (
    SELECT
        person_id,
        min(timestamp) as timestamp,
        breakdown_value
    FROM (
        SELECT
        pdi.person_id as person_id,
        timestamp,
        {breakdown_value} as breakdown_value
        FROM
        events e
        {person_join}
        {groups_join}
        {breakdown_filter}
    )
    GROUP BY person_id, breakdown_value
) AS pdi
GROUP BY day_start, breakdown_value
"""

BREAKDOWN_ACTIVE_USER_INNER_SQL = """
SELECT counts as total, timestamp as day_start, breakdown_value
FROM (
    SELECT d.timestamp, COUNT(DISTINCT person_id) counts, breakdown_value FROM (
        SELECT toStartOfDay(toDateTime(timestamp), %(timezone)s) as timestamp FROM events e WHERE team_id = %(team_id)s {parsed_date_from_prev_range} {parsed_date_to} GROUP BY timestamp
    ) d
    CROSS JOIN (
        SELECT toStartOfDay(toDateTime(timestamp), %(timezone)s) as timestamp, pdi.person_id AS person_id, {breakdown_value} as breakdown_value
        FROM events e
        INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) as pdi
        ON e.distinct_id = pdi.distinct_id
        {person_join}
        {groups_join}
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
FROM events e
{person_join}
{groups_join}
{breakdown_filter}
GROUP BY breakdown_value
ORDER BY breakdown_value
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
