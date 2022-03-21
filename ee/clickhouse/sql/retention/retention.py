RETENTION_BREAKDOWN_SQL = """
    WITH actor_query AS ({actor_query})

    SELECT
        actor_activity.breakdown_values AS breakdown_values,
        actor_activity.intervals_from_base AS intervals_from_base,
        COUNT(DISTINCT actor_activity.actor_id) AS count

    FROM actor_query AS actor_activity

    GROUP BY
        breakdown_values,
        intervals_from_base

    ORDER BY
        breakdown_values,
        intervals_from_base
"""

RETENTION_BREAKDOWN_ACTOR_SQL = """
    WITH %(period)s as period,
         %(breakdown_values)s as breakdown_values_filter,
         %(selected_interval)s as selected_interval,
         returning_event_query as ({returning_event_query}),
         target_event_query as ({target_event_query})

    -- Wrap such that CTE is shared across both sides of the union
    SELECT
        DISTINCT
        breakdown_values,
        intervals_from_base,
        actor_id

    FROM (
        SELECT
            target_event.breakdown_values AS breakdown_values,
            datediff(
                period,
                target_event.event_date,
                returning_event.event_date
            ) AS intervals_from_base,
            returning_event.target AS actor_id

        FROM
            target_event_query AS target_event
            JOIN returning_event_query AS returning_event
                ON returning_event.target = target_event.target

        WHERE
            returning_event.event_date > target_event.event_date

        UNION ALL

        SELECT
            target_event.breakdown_values AS breakdown_values,
            0 AS intervals_from_base,
            target_event.target AS actor_id

        FROM target_event_query AS target_event
    )

    WHERE
        (breakdown_values_filter is NULL OR breakdown_values = breakdown_values_filter)
        AND (selected_interval is NULL OR intervals_from_base = selected_interval)
"""
