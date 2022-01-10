_LIFECYCLE_EVENTS_QUERY = """
    WITH 
        %(interval)s AS selected_period,
        INTERVAL {interval} AS interval_type,
        toDateTime(%(date_from)s) AS selected_date_from,
        toDateTime(%(date_to)s) AS selected_date_to,

        -- NOTE: we need to cast to `DateTime` otherwise for some intervals
        -- we end up with `Date`, which when compared against `e.timestamp`, which
        -- is a `DateTime`, we get incorrect comparison results due to an issue 
        -- with tables indexed by `DateTime`.
        -- See https://github.com/ClickHouse/ClickHouse/issues/5131 for details
        toDateTime(dateTrunc(selected_period, selected_date_from)) AS selected_interval_from,
        toDateTime(dateTrunc(selected_period, selected_date_to)) AS selected_interval_to,

        -- To ensure that we get the right status for the first period in the date range
        -- we need to include the period prior to check if there was activity within it.
        selected_interval_from - INTERVAL {interval} AS previous_interval_from,

        -- TODO: bound these events within the range, and UNION ALL either `person.created_by` 
        --       as the period of activity. This won't be as accurate in terms of lifecycle 
        --       for the specifically requested event, but will be a much smaller query.
        unbounded_filtered_events AS ({event_query}),

        bounded_person_activity_by_period AS (
            SELECT DISTINCT
                person_id,
                dateTrunc(selected_period, events.timestamp) start_of_period

            FROM unbounded_filtered_events events

            WHERE events.timestamp <= selected_interval_to + interval_type
                AND events.timestamp >= previous_interval_from
        )

    -- Pull out the values from the `period_status_pairs` ready for aggregation. We 
    -- don't need to do this, we could update the aggregation query, but it does 
    -- improve the clarity of what the results structure is
    SELECT 
        person_id, 
        period_status_pairs.1 AS start_of_period,
        period_status_pairs.2 AS status

    FROM (
        SELECT 
            person_id, 

            -- We want to put the status of each period onto it's own line, so we 
            -- can easily aggregate over them
            arrayJoin(
                arrayZip(
                    [start_of_period, start_of_period + interval_type],
                    [activity_status, if(next_is_active, '', 'dormant')]
                )
            ) AS period_status_pairs

        FROM (
            /*
                Get periods of person activity, and classify them as 'new', 'returning' or 'resurrecting', 
                plus we get the period just after the `activity` period and check to see if it should be 
                classified as 'dormant'

                NOTE: we could handle 'new', 'returning' or 'resurrecting', and 'dormant' as separate 
                    queries, which might be more sensible, but means we will need to perform one more
                    JOIN on the person_distinct_id table on the right, which means loading into RAM,
                    which means it will considerable increase query time.
            */
            SELECT 
                activity.person_id as person_id,
                activity.start_of_period as start_of_period,
                if(
                    previous_activity.person_id = '00000000-0000-0000-0000-000000000000',
                    'new',
                    if(
                        dateDiff(
                            selected_period, 
                            previous_activity.timestamp, 
                            activity.start_of_period
                        ) > 1,
                        'resurrecting',
                        'returning'
                    )
                ) as activity_status,

                -- If next_period.person_id isn't null value, then it next_period must be active
                next_period.person_id != '00000000-0000-0000-0000-000000000000' AS next_is_active

            FROM bounded_person_activity_by_period activity

                -- Get activity just before the requested `activity` period, needed so we 
                -- can label the activity period either 'new', 'returning' or 'resurrecting'
                ASOF LEFT JOIN unbounded_filtered_events previous_activity
                    ON previous_activity.person_id = activity.person_id 
                        AND activity.start_of_period > previous_activity.timestamp

                -- Get the period immediately after the `activity` period. If that period has no
                -- activity, then it must be 'dormant'
                LEFT JOIN bounded_person_activity_by_period next_period
                ON activity.person_id = next_period.person_id 
                    AND next_period.start_of_period = activity.start_of_period + interval_type

        )

        WHERE period_status_pairs.2 != ''
    )
"""

LIFECYCLE_SQL = f"""
WITH 
    %(interval)s AS selected_period,

    -- enumerate all requested periods, so we can zero fill as needed.
    -- NOTE: we use dateSub interval rather than seconds, which means we can handle,
    -- for instance, month intervals which do not have a fixed number of seconds.
    periods AS (
        SELECT dateSub(
            {{interval_keyword}}, 
            number, 
            dateTrunc(selected_period, toDateTime(%(date_to)s))
        ) AS start_of_period
        FROM numbers(
            dateDiff(
                %(interval)s, 
                dateTrunc(%(interval)s, toDateTime(%(date_from)s)),
                dateTrunc(%(interval)s, toDateTime(%(date_to)s) + INTERVAL {{interval}})
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
        WHERE start_of_period <= toDateTime(%(date_to)s) AND start_of_period >= toDateTime(%(date_from)s)
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
AND dateTrunc(%(interval)s, toDateTime(%(target_date)s)) = start_of_period
LIMIT %(limit)s OFFSET %(offset)s
"""
