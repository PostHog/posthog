RETENTION_SQL = """
SELECT
    datediff(%(period)s, {trunc_func}(toDateTime(%(start_date)s)), reference_event.event_date) as base_interval,
    datediff(%(period)s, reference_event.event_date, {trunc_func}(toDateTime(event_date))) as intervals_from_base,
    COUNT(DISTINCT event.target) count
FROM (
    {returning_event_query}
) event
JOIN (
    {target_event_query}
) reference_event
    ON (event.target = reference_event.target)
WHERE {trunc_func}(event.event_date) > {trunc_func}(reference_event.event_date)
GROUP BY base_interval, intervals_from_base
ORDER BY base_interval, intervals_from_base
"""

RETENTION_BREAKDOWN_SQL = """
    SELECT
        target_event.breakdown_values AS breakdown_values,
        datediff(
            %(period)s, 
            target_event.event_date, 
            dateTrunc(%(period)s, toDateTime(returning_event.event_date))
        ) AS intervals_from_base,
        COUNT(DISTINCT returning_event.target) AS count

    FROM
        ({returning_event_query}) AS returning_event
        JOIN ({target_event_query}) target_event
            ON returning_event.target = target_event.target

    WHERE 
        dateTrunc(%(period)s, returning_event.event_date) >
        dateTrunc(%(period)s, target_event.event_date)

    GROUP BY 
        breakdown_values, 
        intervals_from_base

    ORDER BY 
        breakdown_values, 
        intervals_from_base
"""

RETENTION_PEOPLE_SQL = """
SELECT DISTINCT {actor_field_name}
FROM events e 
{person_join}
where toDateTime(e.timestamp) >= toDateTime(%(start_date)s) AND toDateTime(e.timestamp) <= toDateTime(%(end_date)s)
AND e.team_id = %(team_id)s AND actor_id IN (
    SELECT target FROM ({target_event_query}) as actors
) {returning_query} {filters}
LIMIT 100 OFFSET %(offset)s
"""

INITIAL_INTERVAL_SQL = """
SELECT datediff(%(period)s, {trunc_func}(toDateTime(%(start_date)s)), event_date) event_date,
       count(DISTINCT target) FROM (
    {reference_event_sql}
) GROUP BY event_date ORDER BY event_date
"""


INITIAL_BREAKDOWN_INTERVAL_SQL = """
    SELECT 
        target_event.breakdown_values AS breakdown_values,
        count(DISTINCT target_event.target)
    FROM ({reference_event_sql}) AS target_event
    GROUP BY breakdown_values ORDER BY breakdown_values
"""
