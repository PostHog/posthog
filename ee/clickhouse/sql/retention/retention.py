RETENTION_BREAKDOWN_SQL = """
    SELECT
        actor_activity.breakdown_values AS breakdown_values,
        actor_activity.intervals_from_base AS intervals_from_base,
        COUNT(DISTINCT actor_activity.actor_id) AS count

    FROM ({actor_query}) AS actor_activity

    GROUP BY 
        breakdown_values, 
        intervals_from_base

    ORDER BY 
        breakdown_values, 
        intervals_from_base
"""

RETENTION_BREAKDOWN_ACTOR_SQL = """
    SELECT
        target_event.breakdown_values AS breakdown_values,
        datediff(
            %(period)s, 
            target_event.event_date, 
            dateTrunc(%(period)s, toDateTime(returning_event.event_date))
        ) AS intervals_from_base,
        returning_event.target AS actor_id

    FROM
        ({returning_event_query}) AS returning_event
        JOIN ({target_event_query}) target_event
            ON returning_event.target = target_event.target

    WHERE 
        dateTrunc(%(period)s, returning_event.event_date) >
        dateTrunc(%(period)s, target_event.event_date)
        AND (%(breakdown_values)s is NULL OR breakdown_values = %(breakdown_values)s)

    LIMIT 1 BY actor_id, intervals_from_base

    UNION ALL

    SELECT 
        target_event.breakdown_values AS breakdown_values,
        0 AS intervals_from_base,
        target_event.target AS actor_id

    FROM ({target_event_query}) AS target_event

    WHERE 
        (%(breakdown_values)s is NULL OR breakdown_values = %(breakdown_values)s)
        AND (%(selected_interval)s is NULL OR intervals_from_base = %(selected_interval)s)

    LIMIT 1 BY actor_id
"""
