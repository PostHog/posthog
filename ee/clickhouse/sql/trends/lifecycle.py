_LIFECYCLE_EVENTS_QUERY = """
    WITH 
        %(team_id)s AS current_team,
        %(interval)s AS selected_period,
        INTERVAL {interval} AS interval_type,
        toDateTime(%(date_from)s) AS selected_date_from,
        toDateTime(%(date_to)s) AS selected_date_to,
        dateTrunc(selected_period, selected_date_from) AS selected_interval_from,
        dateTrunc(selected_period, selected_date_to) AS selected_interval_to,
        selected_interval_from - INTERVAL {interval} AS previous_date_from,
        dateDiff(
           selected_period, 
            -- Include the period before the first in the activity consideration
            previous_date_from, 
            selected_interval_to
        ) AS number_of_intervals,

        filtered_events AS (
            SELECT timestamp,
                person_id AS group_id,
                event

            FROM events
                JOIN (
                    SELECT distinct_id, person_id 
                    FROM (
                        SELECT distinct_id, person_id, is_deleted
                        FROM person_distinct_id2
                        WHERE team_id = current_team
                        ORDER BY distinct_id, version DESC
                        LIMIT 1 BY distinct_id
                    ) WHERE is_deleted = 0
                ) person 
                    ON person.distinct_id = events.distinct_id

            WHERE team_id = current_team AND {event_query} {filters}
        ),

        bounded_person_activity AS (
            SELECT
                group_id,
                dateTrunc(selected_period, events.timestamp) start_of_period

            FROM filtered_events events

            WHERE events.timestamp <= selected_date_to + interval_type
                AND events.timestamp >= previous_date_from
                
            LIMIT 1 BY group_id, start_of_period
        )

    SELECT *

    FROM (
        /*
            Get periods of person activity, and classify them as 'new', 'returning' or 'resurrecting'
        */
        SELECT 
            group_id,
            target.start_of_period as start_of_period,
            if(
                previous_activity.group_id = '00000000-0000-0000-0000-000000000000',
                'new',
                if(
                    dateDiff(
                        selected_period, 
                        previous_activity.timestamp, 
                        target.start_of_period
                    ) > 1,
                    'resurrecting',
                    'returning'
                )
            ) as status

        FROM bounded_person_activity target
            ASOF LEFT JOIN filtered_events previous_activity
                ON previous_activity.group_id = target.group_id 
                    AND target.start_of_period > previous_activity.timestamp

        UNION ALL

        /*
            Get periods just after activity, and classify them as 'dormant'
        */
        SELECT 
            group_id,
            activity_before_target.start_of_period + interval_type AS start_of_period,
            'dormant' AS status

        FROM bounded_person_activity activity_before_target
            ASOF LEFT JOIN filtered_events next_activity
                ON activity_before_target.group_id = next_activity.group_id 
                    AND next_activity.timestamp > activity_before_target.start_of_period + interval_type

            WHERE next_activity.group_id = '00000000-0000-0000-0000-000000000000'
                OR dateDiff(
                    selected_period, 
                    activity_before_target.start_of_period, 
                    next_activity.timestamp
                ) > 1
    ) activity_pairs
"""

LIFECYCLE_SQL = f"""
WITH %(interval)s AS selected_period

SELECT groupArray(start_of_period) as date, groupArray(counts) as data, status FROM (
    SELECT if(status = 'dormant', toInt64(SUM(counts)) * toInt16(-1), toInt64(SUM(counts))) as counts, start_of_period, status
    FROM (
        SELECT ticks.start_of_period as start_of_period, toUInt16(0) AS counts, status

        FROM (
            -- Generates all the intervals/ticks in the date range
            -- NOTE: we build this range by including successive intervals back from the
            --       upper bound, then including the lower bound in the query also.

            SELECT
                dateTrunc(
                    selected_period,
                    toDateTime(%(date_to)s) - number * %(seconds_in_interval)s
                ) as start_of_period
            FROM numbers(%(num_intervals)s)
            UNION ALL
            SELECT dateTrunc(selected_period, toDateTime(%(date_from)s)) as start_of_period
        ) as ticks

        CROSS JOIN (
            SELECT status
            FROM (
                SELECT ['new', 'returning', 'resurrecting', 'dormant'] as status
            ) ARRAY JOIN status
        ) as sec
        ORDER BY status, start_of_period

        UNION ALL

        SELECT start_of_period, count(DISTINCT group_id) counts, status
        FROM ({_LIFECYCLE_EVENTS_QUERY})
        WHERE start_of_period <= toDateTime(%(date_to)s) AND start_of_period >= toDateTime(%(date_from)s)
        GROUP BY start_of_period, status
    )
    GROUP BY start_of_period, status
    ORDER BY start_of_period ASC
)
GROUP BY status
"""

LIFECYCLE_PEOPLE_SQL = f"""
SELECT group_id
FROM ({_LIFECYCLE_EVENTS_QUERY}) e
WHERE status = %(status)s
AND {{trunc_func}}(toDateTime(%(target_date)s)) = start_of_period
LIMIT %(limit)s OFFSET %(offset)s
"""
