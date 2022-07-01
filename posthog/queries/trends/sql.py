VOLUME_SQL = """
SELECT {aggregate_operation} as data, {interval}(toDateTime(timestamp), {start_of_week_fix} %(timezone)s) as date FROM ({event_query}) GROUP BY date
"""

VOLUME_TOTAL_AGGREGATE_SQL = """
SELECT {aggregate_operation} as data FROM ({event_query}) events
"""

SESSION_VOLUME_TOTAL_AGGREGATE_SQL = """
SELECT {aggregate_operation} as data FROM (
    SELECT any(session_duration) as session_duration FROM ({event_query}) events GROUP BY $session_id
)
"""

SESSION_DURATION_VOLUME_SQL = """
SELECT {aggregate_operation} as data, date FROM (
    SELECT {interval}(toDateTime(timestamp), {start_of_week_fix} %(timezone)s) as date, any(session_duration) as session_duration
    FROM ({event_query})
    GROUP BY $session_id, date
) GROUP BY date
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

TOP_ELEMENTS_ARRAY_OF_KEY_SQL = """
SELECT groupArray(value) FROM (
    SELECT
        {value_expression},
        {aggregate_operation} as count
    FROM events e
    {person_join_clauses}
    {groups_join_clauses}
    {sessions_join_clauses}
    WHERE
        team_id = %(team_id)s {entity_query} {parsed_date_from} {parsed_date_to} {prop_filters}
    GROUP BY value
    ORDER BY count DESC, value DESC
    LIMIT %(limit)s OFFSET %(offset)s
)
"""

HISTOGRAM_ELEMENTS_ARRAY_OF_KEY_SQL = """
SELECT {bucketing_expression} FROM (
    SELECT
        {value_expression},
        {aggregate_operation} as count
    FROM events e
    {person_join_clauses}
    {groups_join_clauses}
    {sessions_join_clauses}
    WHERE
        team_id = %(team_id)s {entity_query} {parsed_date_from} {parsed_date_to} {prop_filters}
    GROUP BY value
)
"""


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
{sessions_join}
{breakdown_filter}
GROUP BY day_start, breakdown_value
"""

SESSION_BREAKDOWN_INNER_SQL = """
SELECT
    {aggregate_operation} as total, day_start, breakdown_value
FROM (
    SELECT any(session_duration) as session_duration, day_start, breakdown_value FROM (
        SELECT $session_id, session_duration, {interval_annotation}(timestamp, {start_of_week_fix} %(timezone)s) as day_start,
            {breakdown_value} as breakdown_value
        FROM events e
        {person_join}
        {groups_join}
        {sessions_join}
        {breakdown_filter}
    )
    GROUP BY $session_id, day_start, breakdown_value
)
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
        {person_id_alias}.person_id as person_id,
        timestamp,
        {breakdown_value} as breakdown_value
        FROM
        events e
        {person_join}
        {groups_join}
        {sessions_join}
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
        SELECT toStartOfDay(toDateTime(timestamp), %(timezone)s) as timestamp, {person_id_alias}.person_id AS person_id, {breakdown_value} as breakdown_value
        FROM events e
        {person_join}
        {groups_join}
        {sessions_join}
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
{sessions_join_condition}
{breakdown_filter}
GROUP BY breakdown_value
ORDER BY breakdown_value
"""


BREAKDOWN_HISTOGRAM_AGGREGATE_QUERY_SQL = """
SELECT histogram(%(bin_count)s)({aggregate_operation}) AS histogram
SELECT {aggregate_operation} AS total, {breakdown_value} AS breakdown_value
FROM events e
{person_join}
{groups_join}
{sessions_join_condition}
{breakdown_filter}
GROUP BY breakdown_value
ORDER BY breakdown_value
"""


SESSION_MATH_BREAKDOWN_AGGREGATE_QUERY_SQL = """
SELECT {aggregate_operation} AS total, breakdown_value
FROM (
    SELECT any(session_duration) as session_duration, breakdown_value FROM (
        SELECT $session_id, session_duration, {breakdown_value} AS breakdown_value FROM
            events e
            {person_join}
            {groups_join}
            {sessions_join_condition}
            {breakdown_filter}
        )
    GROUP BY $session_id, breakdown_value
)
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

BREAKDOWN_HISTOGRAM_PROP_JOIN_SQL = """
WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to}
  {actions_query}
"""

BREAKDOWN_COHORT_JOIN_SQL = """
INNER JOIN (
    {cohort_queries}
) ep
ON e.distinct_id = ep.distinct_id where team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to} {actions_query}
"""

_LIFECYCLE_EVENTS_QUERY = """
SELECT
    person_id,

    /*
        We want to put the status of each period onto it's own line, so we
        can easily aggregate over them. With the inner query we end up with a structure like:

        person_id  |  period_of_activity  | status_of_activity  | dormant_status_of_period_after_activity

        However, we want to have something of the format:

        person_id  | period_of_activity          |  status_of_activity
        person_id  | period_just_after_activity  |  dormant_status_of_period_after_activity

        such that we can simply aggregate over person_id, period.
    */
    arrayJoin(
        arrayZip(
            [period, period + INTERVAL 1 {interval_expr}],
            [initial_status, if(next_is_active, '', 'dormant')]
        )
    ) AS period_status_pairs,
    period_status_pairs.1 as start_of_period,
    period_status_pairs.2 as status
FROM (
    SELECT
        person_id,
        period,
        created_at,
        if(
            dateTrunc(%(interval)s, toDateTime(created_at, %(timezone)s)) = period,
            'new',
            if(
                previous_activity + INTERVAL 1 {interval_expr} = period,
                'returning',
                'resurrecting'
            )
        ) AS initial_status,
        period + INTERVAL 1 {interval_expr} = following_activity AS next_is_active,
        previous_activity,
        following_activity
    FROM (
        SELECT
            person_id,
            any(period) OVER (PARTITION BY person_id ORDER BY period ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING) as previous_activity,
            period,
            any(period) OVER (PARTITION BY person_id ORDER BY period ROWS BETWEEN 1 FOLLOWING AND 1 FOLLOWING) as following_activity,
            created_at
        FROM ({events_query})
    )
)
WHERE period_status_pairs.2 != ''
SETTINGS allow_experimental_window_functions = 1
"""

LIFECYCLE_SQL = f"""
WITH
    %(interval)s AS selected_period,

    -- enumerate all requested periods, so we can zero fill as needed.
    -- NOTE: we use dateSub interval rather than seconds, which means we can handle,
    -- for instance, month intervals which do not have a fixed number of seconds.
    periods AS (
        SELECT dateSub(
            {{interval_expr}},
            number,
            dateTrunc(selected_period, toDateTime(%(date_to)s, %(timezone)s))
        ) AS start_of_period
        FROM numbers(
            dateDiff(
                %(interval)s,
                dateTrunc(%(interval)s, toDateTime(%(date_from)s)),
                dateTrunc(%(interval)s, toDateTime(%(date_to)s) + INTERVAL 1 {{interval_expr}})
            )
        )
    )
SELECT
    groupArray(start_of_period) as date,
    groupArray(counts) as data,
    status
FROM (
    SELECT if(
            status = 'dormant',
            toInt64(SUM(counts)) * toInt16(-1),
            toInt64(SUM(counts))
        ) as counts,
        start_of_period,
        status

    FROM (
        SELECT periods.start_of_period as start_of_period, toUInt16(0) AS counts, status

        FROM periods

        -- Zero fill for each status
        CROSS JOIN (
            SELECT status
            FROM (
                SELECT ['new', 'returning', 'resurrecting', 'dormant'] as status
            ) ARRAY JOIN status
        ) as sec
        ORDER BY status, start_of_period

        UNION ALL

        SELECT start_of_period, count(DISTINCT person_id) counts, status
        FROM ({_LIFECYCLE_EVENTS_QUERY})
        WHERE start_of_period <= dateTrunc(%(interval)s, toDateTime(%(date_to)s, %(timezone)s))
          AND start_of_period >= dateTrunc(%(interval)s, toDateTime(%(date_from)s, %(timezone)s))
        GROUP BY start_of_period, status
    )
    GROUP BY start_of_period, status
    ORDER BY start_of_period ASC
)
GROUP BY status
"""

LIFECYCLE_PEOPLE_SQL = f"""
SELECT person_id
FROM ({_LIFECYCLE_EVENTS_QUERY}) e
WHERE status = %(status)s
AND dateTrunc(%(interval)s, toDateTime(%(target_date)s, %(timezone)s)) = start_of_period
LIMIT %(limit)s OFFSET %(offset)s
"""
