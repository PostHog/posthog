VOLUME_SQL = """
SELECT
    {aggregate_operation} AS total,
    {timestamp_truncated} AS date
{event_query_base}
GROUP BY date
"""

VOLUME_AGGREGATE_SQL = """
SELECT {aggregate_operation} AS total
{event_query_base}
"""

VOLUME_PER_ACTOR_SQL = """
SELECT {aggregate_operation} AS total, date FROM (
    SELECT
        count() AS intermediate_count,
        {timestamp_truncated} AS date
    {event_query_base}
    GROUP BY {aggregator}, date
) GROUP BY date
"""

VOLUME_PER_ACTOR_AGGREGATE_SQL = """
SELECT {aggregate_operation} AS total FROM (
    SELECT
        count() AS intermediate_count
    {event_query_base}
    GROUP BY {aggregator}
) events
"""

SESSION_DURATION_SQL = """
SELECT {aggregate_operation} AS total, date FROM (
    SELECT
        {timestamp_truncated} as date,
        any(sessions.session_duration) as session_duration
    {event_query_base}
    GROUP BY e."$session_id", date
) GROUP BY date
"""

SESSION_DURATION_AGGREGATE_SQL = """
SELECT {aggregate_operation} AS total FROM (
    SELECT any(session_duration) as session_duration
    {event_query_base}
    GROUP BY e."$session_id"
)
"""


ACTIVE_USERS_SQL = """
SELECT counts AS total, timestamp AS day_start FROM (
    SELECT d.timestamp, COUNT(DISTINCT actor_id) AS counts FROM (
        /* We generate a table of periods to match events against. This has to be synthesized from `numbers`
           and not `events`, because we cannot rely on there being an event for each period (this assumption previously
           caused active user counts to be off for sparse events). */
        SELECT toDateTime({date_to_truncated} - {interval_func}(number), %(timezone)s) AS timestamp
        FROM numbers(dateDiff(%(interval)s, {date_from_active_users_adjusted_truncated}, toDateTime(%(date_to)s, %(timezone)s)))
    ) d
    /* In Postgres we'd be able to do a non-cross join with multiple inequalities (in this case, <= along with >),
       but this is not possible in ClickHouse as of 2022.10 (ASOF JOIN isn't fit for this either). */
    CROSS JOIN (
        SELECT
            toTimeZone(toDateTime(timestamp, 'UTC'), %(timezone)s) AS timestamp,
            {aggregator} AS actor_id
        {event_query_base}
        GROUP BY timestamp, actor_id
    ) e WHERE e.timestamp <= d.timestamp + INTERVAL 1 DAY AND e.timestamp > d.timestamp - INTERVAL {prev_interval}
    GROUP BY d.timestamp
    ORDER BY d.timestamp
) WHERE 1 = 1 {parsed_date_from} {parsed_date_to}
"""

ACTIVE_USERS_AGGREGATE_SQL = """
SELECT
    {aggregate_operation} AS total
{event_query_base}
"""

FINAL_TIME_SERIES_SQL = """
SELECT groupArray(day_start) as date, groupArray({aggregate}) AS total FROM (
    SELECT {smoothing_operation} AS count, day_start
    FROM (
        {null_sql}
        UNION ALL
        {content_sql}
    )
    GROUP BY day_start
    ORDER BY day_start
)
"""

CUMULATIVE_SQL = """
SELECT {actor_expression} AS actor_id, min(timestamp) AS first_seen_timestamp
{event_query_base}
GROUP BY actor_id
"""

TOP_ELEMENTS_ARRAY_OF_KEY_SQL = """
    SELECT
        {breakdown_expression},
        {aggregate_operation} as count
    FROM events e
    {sample_clause}
    {person_join_clauses}
    {groups_join_clauses}
    {sessions_join_clauses}
    WHERE
        team_id = %(team_id)s {entity_query} {parsed_date_from} {parsed_date_to} {prop_filters} {null_person_filter}
    GROUP BY value
    ORDER BY count DESC, value DESC
    LIMIT %(limit)s OFFSET %(offset)s
"""

HISTOGRAM_ELEMENTS_ARRAY_OF_KEY_SQL = """
SELECT {bucketing_expression} FROM (
    SELECT
        {breakdown_expression},
        {aggregate_operation} as count
    FROM events e
    {sample_clause}
    {person_join_clauses}
    {groups_join_clauses}
    {sessions_join_clauses}
    WHERE
        team_id = %(team_id)s {entity_query} {parsed_date_from} {parsed_date_to} {prop_filters} {null_person_filter}
    GROUP BY value
)
"""


BREAKDOWN_QUERY_SQL = """
SELECT groupArray(day_start) as date, groupArray(count) AS total, breakdown_value FROM (
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
                {date_to_truncated} - {interval_func}(number) as day_start
                FROM numbers({num_intervals})
                UNION ALL
                SELECT {date_from_truncated} as day_start
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
    {timestamp_truncated} as day_start,
    {breakdown_value} as breakdown_value
FROM events e
{sample_clause}
{person_join}
{groups_join}
{sessions_join}
{breakdown_filter}
{null_person_filter}
GROUP BY day_start, breakdown_value
"""

VOLUME_PER_ACTOR_BREAKDOWN_INNER_SQL = """
SELECT
    {aggregate_operation} AS total, day_start, breakdown_value
FROM (
    SELECT
        COUNT(*) AS intermediate_count,
        {aggregator},
        {timestamp_truncated} AS day_start,
        {breakdown_value} as breakdown_value
    FROM events AS e
    {sample_clause}
    {person_join}
    {groups_join}
    {sessions_join}
    {breakdown_filter}
    {null_person_filter}
    GROUP BY {aggregator}, day_start, breakdown_value
)
GROUP BY day_start, breakdown_value
"""

VOLUME_PER_ACTOR_BREAKDOWN_AGGREGATE_SQL = """
SELECT {aggregate_operation} AS total, breakdown_value
FROM (
    SELECT
        COUNT(*) AS intermediate_count,
        {aggregator}, {breakdown_value} AS breakdown_value
    FROM events AS e
    {sample_clause}
    {person_join}
    {groups_join}
    {sessions_join_condition}
    {breakdown_filter}
    GROUP BY {aggregator}, breakdown_value
)
GROUP BY breakdown_value
ORDER BY breakdown_value
"""

SESSION_DURATION_BREAKDOWN_INNER_SQL = """
SELECT
    {aggregate_operation} as total, day_start, breakdown_value
FROM (
    SELECT any(session_duration) as session_duration, day_start, breakdown_value FROM (
        SELECT {event_sessions_table_alias}.$session_id, session_duration, {timestamp_truncated} as day_start,
            {breakdown_value} as breakdown_value
        FROM events AS e
        {sample_clause}
        {person_join}
        {groups_join}
        {sessions_join}
        {breakdown_filter}
        {null_person_filter}
    )
    GROUP BY {event_sessions_table_alias}.$session_id, day_start, breakdown_value
)
GROUP BY day_start, breakdown_value
"""

BREAKDOWN_CUMULATIVE_INNER_SQL = """
SELECT
    {aggregate_operation} as total,
    {timestamp_truncated} as day_start,
    breakdown_value
FROM (
    SELECT
        person_id,
        min(timestamp) as timestamp,
        breakdown_value
    FROM (
        SELECT
        {person_id_alias} as person_id,
        timestamp,
        {breakdown_value} as breakdown_value
        FROM
        events e
        {sample_clause}
        {person_join}
        {groups_join}
        {sessions_join}
        {breakdown_filter}
        {null_person_filter}
    )
    GROUP BY person_id, breakdown_value
) AS pdi
GROUP BY day_start, breakdown_value
"""

BREAKDOWN_ACTIVE_USER_INNER_SQL = """
SELECT counts AS total, timestamp AS day_start, breakdown_value
FROM (
    SELECT d.timestamp, COUNT(DISTINCT person_id) counts, breakdown_value FROM (
        SELECT toStartOfDay(toTimeZone(toDateTime(timestamp, 'UTC'), %(timezone)s)) AS timestamp FROM events e WHERE team_id = %(team_id)s {parsed_date_from_prev_range} {parsed_date_to} GROUP BY timestamp
    ) d
    CROSS JOIN (
        SELECT
            toStartOfDay(toTimeZone(toDateTime(timestamp, 'UTC'), %(timezone)s)) AS timestamp,
            {person_id_alias} AS person_id,
            {breakdown_value} AS breakdown_value
        FROM events e
        {sample_clause}
        {person_join}
        {groups_join}
        {sessions_join}
        {conditions}
        {null_person_filter}
        GROUP BY timestamp, person_id, breakdown_value
    ) e
    WHERE e.timestamp <= d.timestamp AND e.timestamp > d.timestamp - INTERVAL {prev_interval}
    GROUP BY d.timestamp, breakdown_value
    ORDER BY d.timestamp
) WHERE 11111 = 11111 {parsed_date_from} {parsed_date_to}
"""

BREAKDOWN_ACTIVE_USER_AGGREGATE_SQL = """
SELECT
    {aggregate_operation} AS total, {breakdown_value} as breakdown_value
FROM events AS e
{sample_clause}
{person_join}
{groups_join}
{sessions_join}
{conditions}
{null_person_filter}
{parsed_date_from_prev_range} - INTERVAL {prev_interval} {parsed_date_to}
GROUP BY breakdown_value
ORDER BY breakdown_value
"""

BREAKDOWN_AGGREGATE_QUERY_SQL = """
SELECT {aggregate_operation} AS total, {breakdown_value} AS breakdown_value
FROM events e
{sample_clause}
{person_join}
{groups_join}
{sessions_join_condition}
{breakdown_filter}
GROUP BY breakdown_value
ORDER BY breakdown_value
"""


SESSION_DURATION_BREAKDOWN_AGGREGATE_SQL = """
SELECT {aggregate_operation} AS total, breakdown_value
FROM (
    SELECT any(session_duration) as session_duration, breakdown_value FROM (
        SELECT {event_sessions_table_alias}.$session_id, session_duration, {breakdown_value} AS breakdown_value FROM
            events e
            {sample_clause}
            {person_join}
            {groups_join}
            {sessions_join_condition}
            {breakdown_filter}
        )
    GROUP BY {event_sessions_table_alias}.$session_id, breakdown_value
)
GROUP BY breakdown_value
ORDER BY breakdown_value
"""

BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL = """
WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from_prev_range} {parsed_date_to} {actions_query} {null_person_filter}
"""

BREAKDOWN_PROP_JOIN_WITH_OTHER_SQL = """
WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to} {null_person_filter}
  {actions_query}
"""

BREAKDOWN_PROP_JOIN_SQL = """
WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to} {null_person_filter}
  AND {breakdown_value_expr} in (%(values)s)
  {actions_query}
"""

BREAKDOWN_HISTOGRAM_PROP_JOIN_SQL = """
WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to} {numeric_property_filter} {null_person_filter}
  {actions_query}
"""

BREAKDOWN_COHORT_JOIN_SQL = """
INNER JOIN (
    {cohort_queries}
) ep
ON e.distinct_id = ep.distinct_id where team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to} {actions_query} {null_person_filter}
"""

LIFECYCLE_EVENTS_QUERY = """
SELECT
    {person_column} as person_id,
    arraySort(groupUniqArray(dateTrunc(%(interval)s, toTimeZone(toDateTime(events.timestamp, %(timezone)s), %(timezone)s)))) AS all_activity,
    arrayPopBack(arrayPushFront(all_activity, dateTrunc(%(interval)s, toTimeZone(toDateTime(min({created_at_clause}), %(timezone)s), %(timezone)s)))) as previous_activity,
    arrayPopFront(arrayPushBack(all_activity, dateTrunc(%(interval)s, toDateTime('1970-01-01')))) as following_activity,
    arrayMap((previous,current, index) -> if(
        previous = current, 'new', if(
                current - INTERVAL 1 {interval} = previous AND index != 1,
                'returning',
                'resurrecting'
            )
        ) , previous_activity, all_activity, arrayEnumerate(all_activity)) as initial_status,
    arrayMap((current, next) -> if(
        current + INTERVAL 1 {interval} = next,
        '',
        'dormant'
    ), all_activity, following_activity) as dormant_status,
    arrayMap(x -> x + INTERVAL 1 {interval} , arrayFilter((current, is_dormant) -> is_dormant = 'dormant', all_activity, dormant_status)) as dormant_periods,
    arrayMap(x -> 'dormant', dormant_periods) as dormant_label,
    arrayConcat(arrayZip(all_activity, initial_status), arrayZip(dormant_periods, dormant_label)) as temp_concat,
    arrayJoin(temp_concat) as period_status_pairs,
    period_status_pairs.1 as start_of_period,
    period_status_pairs.2 as status,
    toDateTime(min({created_at_clause}), %(timezone)s) AS created_at
FROM events AS {event_table_alias}
{sample_clause}
{distinct_id_query}
{person_query}
{groups_query}


WHERE team_id = %(team_id)s
{entity_filter}
{entity_prop_query}
{date_query}
{prop_query}

{null_person_filter}
GROUP BY {person_column}

"""

LIFECYCLE_SQL = """
WITH
    %(interval)s AS selected_period,

    -- enumerate all requested periods, so we can zero fill as needed.
    -- NOTE: we use dateSub interval rather than seconds, which means we can handle,
    -- for instance, month intervals which do not have a fixed number of seconds.
    periods AS (
        SELECT dateSub(
            {interval_expr},
            number,
            dateTrunc(selected_period, toDateTime(%(date_to)s, %(timezone)s))
        ) AS start_of_period
        FROM numbers(
            dateDiff(
                %(interval)s,
                dateTrunc(%(interval)s, toDateTime(%(date_from)s, %(timezone)s)),
                dateTrunc(%(interval)s, toDateTime(%(date_to)s, %(timezone)s) + INTERVAL 1 {interval_expr})
            )
        )
    )
SELECT groupArray(start_of_period) AS date,
        groupArray(counts) AS total,
        status
FROM (
    SELECT
        if(
            status = 'dormant',
            toInt64(SUM(counts)) * toInt16(-1),
            toInt64(SUM(counts))
        ) as counts,
        start_of_period,
        status
    FROM (
        SELECT
            periods.start_of_period as start_of_period,
            toUInt16(0) AS counts,
            status
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
        SELECT
            start_of_period, count(DISTINCT person_id) counts, status
        FROM ({events_query})
        GROUP BY start_of_period, status
    )
    WHERE start_of_period <= dateTrunc(%(interval)s, toDateTime(%(date_to)s, %(timezone)s))
        AND start_of_period >= dateTrunc(%(interval)s, toDateTime(%(date_from)s, %(timezone)s))
    GROUP BY start_of_period, status
    ORDER BY start_of_period ASC
)
GROUP BY status
"""


LIFECYCLE_PEOPLE_SQL = """
SELECT DISTINCT person_id as actor_id
FROM ({events_query}) e
WHERE status = %(status)s
AND dateTrunc(%(interval)s, toDateTime(%(target_date)s, %(timezone)s)) = start_of_period
{limit}
{offset}
"""
