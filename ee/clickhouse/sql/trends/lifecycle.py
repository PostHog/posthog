_LIFECYCLE_EVENTS_QUERY = """
WITH person_activity_including_previous_period AS (
    SELECT DISTINCT 
        person_id, 
        {trunc_func}(events.timestamp) start_of_period 

    FROM events
        JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi 
            ON events.distinct_id = pdi.distinct_id

    WHERE team_id = %(team_id)s AND {event_query} {filters}

    GROUP BY 
        person_id, 
        start_of_period
        
    HAVING 
        start_of_period <= toDateTime(%(date_to)s) 
        AND start_of_period >= toDateTime(%(prev_date_from)s)

), person_activity_as_array AS (
    SELECT DISTINCT 
        person_id, 
        groupArray({trunc_func}(events.timestamp)) start_of_period 

    FROM events
        JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi 
            ON events.distinct_id = pdi.distinct_id

    WHERE 
        team_id = %(team_id)s 
        AND {event_query} {filters}
        AND toDateTime(events.timestamp) <= toDateTime(%(date_to)s) 
        AND {trunc_func}(events.timestamp) >= toDateTime(%(date_from)s)
        
    GROUP BY person_id
), periods AS (
    SELECT 
        {trunc_func}(toDateTime(%(date_to)s) - number * %(seconds_in_interval)s) AS start_of_period 
        
    FROM numbers(%(num_intervals)s)
)

SELECT 
    activity_pairs.person_id AS person_id,
    activity_pairs.initial_period AS initial_period,
    activity_pairs.next_period AS next_period, 
    if(
        initial_period = toDateTime('0000-00-00 00:00:00'), 
        'dormant', 
        if(
            next_period = initial_period + INTERVAL {interval}, 
            'returning', 
            if(
                next_period > earliest + INTERVAL {interval}, 
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
        initial_period, 
        min(next_period) as next_period 

    FROM (
        SELECT 
            person_id, 
            base.start_of_period as initial_period, 
            subsequent.start_of_period as next_period

        FROM person_activity_including_previous_period base
            JOIN person_activity_including_previous_period subsequent 
                ON base.person_id = subsequent.person_id

        WHERE subsequent.start_of_period > base.start_of_period
    )

    GROUP BY 
        person_id, 
        initial_period

    UNION ALL

    /* 
        Get the first active period for each user within the extended range 
        i.e. including the previous period
        
        NOTE: initial_period and next_period are the same
    */ 
    SELECT
        base.person_id, 
        min(base.start_of_period) as initial_period, 
        min(base.start_of_period) as next_period 
        
    FROM person_activity_including_previous_period base
    GROUP BY person_id

    UNION ALL

    /*
        Get activity status rows for all dormant periods and all persons
    */
    SELECT 
        person_id, 
        initial_period, 
        next_period 

    FROM (
        SELECT 
            person_activity.person_id AS person_id, 

            -- Use datetime null value as marker that this refers to dormant
            toDateTime('0000-00-00 00:00:00') as initial_period, 
            periods.start_of_period as next_period

        FROM person_activity_as_array as person_activity
            CROSS JOIN periods

        WHERE has(person_activity.start_of_period, periods.start_of_period) = 0

        ORDER BY 
            person_id, 
            periods.start_of_period ASC
    ) 
    
    WHERE
        -- exclude first period of dormant
        ( 
            (empty(toString(neighbor(person_id, -1))) 
            OR neighbor(person_id, -1) != person_id
        ) 
        AND next_period != {trunc_func}(toDateTime(%(date_from)s) + INTERVAL {interval} - INTERVAL {sub_interval}))
        OR (
            (neighbor(person_id, -1) = person_id) 
            AND neighbor(next_period, -1) < next_period - INTERVAL {interval}
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
SELECT groupArray(start_of_period) as date, groupArray(counts) as data, status FROM (
    SELECT if(status = 'dormant', toInt64(SUM(counts)) * toInt16(-1), toInt64(SUM(counts))) as counts, start_of_period, status
    FROM (
        SELECT ticks.start_of_period as start_of_period, toUInt16(0) AS counts, status

        FROM (
            -- Generates all the intervals/ticks in the date range
            -- NOTE: we build this range by including successive intervals back from the
            --       upper bound, then including the lower bound in the query also.

            SELECT
                {{trunc_func}}(
                    toDateTime(%(date_to)s) - number * %(seconds_in_interval)s
                ) as start_of_period
            FROM numbers(%(num_intervals)s)
            UNION ALL
            SELECT {{trunc_func}}(toDateTime(%(date_from)s)) as start_of_period
        ) as ticks

        CROSS JOIN (
            SELECT status
            FROM (
                SELECT ['new', 'returning', 'resurrecting', 'dormant'] as status
            ) ARRAY JOIN status
        ) as sec
        ORDER BY status, start_of_period

        UNION ALL

        SELECT next_period, count(DISTINCT person_id) counts, status
        FROM ({_LIFECYCLE_EVENTS_QUERY})
        WHERE next_period <= toDateTime(%(date_to)s) AND next_period >= toDateTime(%(date_from)s)
        GROUP BY next_period, status
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
AND {{trunc_func}}(toDateTime(%(target_date)s)) = next_period
LIMIT %(limit)s OFFSET %(offset)s
"""
