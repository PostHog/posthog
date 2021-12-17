_LIFECYCLE_EVENTS_QUERY = """
WITH person_activity_including_previous_period AS (
    SELECT DISTINCT 
        person_id, 
        {trunc_func}(events.timestamp) day 

    FROM events
        JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi 
            ON events.distinct_id = pdi.distinct_id

    WHERE team_id = %(team_id)s AND {event_query} {filters}

    GROUP BY 
        person_id, 
        day
        
    HAVING 
        day <= toDateTime(%(date_to)s) 
        AND day >= toDateTime(%(prev_date_from)s)

), person_activity_as_array AS (
    SELECT DISTINCT 
        person_id, 
        groupArray({trunc_func}(events.timestamp)) day 

    FROM events
        JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi 
            ON events.distinct_id = pdi.distinct_id

    WHERE 
        team_id = %(team_id)s 
        AND {event_query} {filters}
        AND toDateTime(events.timestamp) <= toDateTime(%(date_to)s) 
        AND {trunc_func}(events.timestamp) >= toDateTime(%(date_from)s)
        
    GROUP BY person_id
), period_starts AS (
    SELECT 
        {trunc_func}(toDateTime(%(date_to)s) - number * %(seconds_in_interval)s) AS day_start 
        
    FROM numbers(%(num_intervals)s)
)

SELECT 
    activity_pairs.person_id AS person_id,
    activity_pairs.base_day AS base_day,
    activity_pairs.subsequent_day AS subsequent_day, 
    if(
        base_day = toDateTime('0000-00-00 00:00:00'), 
        'dormant', 
        if(
            subsequent_day = base_day + INTERVAL {interval}, 
            'returning', 
            if(
                subsequent_day > earliest + INTERVAL {interval}, 
                'resurrecting', 
                'new'
            )
        )
    ) as status

FROM (
    /*
         Get person period activity paired with the next adjacent period activity
    */
    SELECT 
        person_id, 
        base_day, 
        min(subsequent_day) as subsequent_day 

    FROM (
        SELECT 
            person_id, 
            base.day as base_day, 
            subsequent.day as subsequent_day

        FROM person_activity_including_previous_period base
            JOIN person_activity_including_previous_period subsequent 
                ON base.person_id = subsequent.person_id

        WHERE subsequent.day > base.day
    )

    GROUP BY 
        person_id, 
        base_day

    UNION ALL

    /* 
        Get the first active period for each user within the extended range 
        i.e. including the previous period
        
        NOTE: base_day and subsequent_day are the same
    */ 
    SELECT
        base.person_id, 
        min(base.day) as base_day, 
        min(base.day) as subsequent_day 
        
    FROM person_activity_including_previous_period base
    GROUP BY person_id

    UNION ALL

    /*
        Get activity status rows for all dormant periods and all persons
    */
    SELECT 
        person_id, 
        base_day, 
        subsequent_day 

    FROM (
        SELECT 
            person_activity.person_id AS person_id, 

            -- Use datetime null value as marker that this refers to dormant
            toDateTime('0000-00-00 00:00:00') as base_day, 
            period_starts.day_start as subsequent_day

        FROM person_activity_as_array as person_activity
            CROSS JOIN period_starts

        WHERE has(person_activity.day, period_starts.day_start) = 0

        ORDER BY 
            person_id, 
            period_starts.day_start ASC
    ) 
    
    WHERE
        -- exclude first period ofr dormant
        ( 
            (empty(toString(neighbor(person_id, -1))) 
            OR neighbor(person_id, -1) != person_id
        ) 
        AND subsequent_day != {trunc_func}(toDateTime(%(date_from)s) + INTERVAL {interval} - INTERVAL {sub_interval}))
        OR (
            (neighbor(person_id, -1) = person_id) 
            AND neighbor(subsequent_day, -1) < subsequent_day - INTERVAL {interval}
        )
) activity_pairs

    -- Get the earliest event for each person
    JOIN (
        SELECT DISTINCT 
            person_id, 
            {trunc_func}(min(events.timestamp)) earliest 
        FROM events

            JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi 
                ON events.distinct_id = pdi.distinct_id

        WHERE team_id = %(team_id)s AND {event_query} {filters}
        GROUP BY person_id
    ) earliest ON activity_pairs.person_id = earliest.person_id

"""

LIFECYCLE_SQL = f"""
SELECT groupArray(day_start) as date, groupArray(counts) as data, status FROM (
    SELECT if(status = 'dormant', toInt64(SUM(counts)) * toInt16(-1), toInt64(SUM(counts))) as counts, day_start, status
    FROM (
        SELECT ticks.day_start as day_start, toUInt16(0) AS counts, status

        FROM (
            -- Generates all the intervals/ticks in the date range
            -- NOTE: we build this range by including successive intervals back from the
            --       upper bound, then including the lower bound in the query also.

            SELECT
                {{trunc_func}}(
                    toDateTime(%(date_to)s) - number * %(seconds_in_interval)s
                ) as day_start
            FROM numbers(%(num_intervals)s)
            UNION ALL
            SELECT {{trunc_func}}(toDateTime(%(date_from)s)) as day_start
        ) as ticks

        CROSS JOIN (
            SELECT status
            FROM (
                SELECT ['new', 'returning', 'resurrecting', 'dormant'] as status
            ) ARRAY JOIN status
        ) as sec
        ORDER BY status, day_start

        UNION ALL

        SELECT subsequent_day, count(DISTINCT person_id) counts, status
        FROM ({_LIFECYCLE_EVENTS_QUERY})
        WHERE subsequent_day <= toDateTime(%(date_to)s) AND subsequent_day >= toDateTime(%(date_from)s)
        GROUP BY subsequent_day, status
    )
    GROUP BY day_start, status
    ORDER BY day_start ASC
)
GROUP BY status
"""

LIFECYCLE_PEOPLE_SQL = f"""
SELECT person_id
FROM ({_LIFECYCLE_EVENTS_QUERY}) e
WHERE status = %(status)s
AND {{trunc_func}}(toDateTime(%(target_date)s)) = subsequent_day
LIMIT %(limit)s OFFSET %(offset)s
"""
