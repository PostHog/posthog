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

REFERENCE_EVENT_SQL = """
SELECT DISTINCT
{trunc_func}(e.timestamp) as event_date,
pdi.person_id as person_id,
e.uuid as uuid,
e.event as event
from events e JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi on e.distinct_id = pdi.distinct_id
where toDateTime(e.timestamp) >= toDateTime(%(reference_start_date)s) AND toDateTime(e.timestamp) <= toDateTime(%(reference_end_date)s)
AND e.team_id = %(team_id)s {target_query} {filters}
"""

REFERENCE_EVENT_UNIQUE_SQL = """
SELECT DISTINCT
min({trunc_func}(e.timestamp)) as event_date,
pdi.person_id as person_id,
argMin(e.uuid, {trunc_func}(e.timestamp)) as min_uuid,
argMin(e.event, {trunc_func}(e.timestamp)) as min_event
from events e JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi on e.distinct_id = pdi.distinct_id
WHERE e.team_id = %(team_id)s {target_query} {filters}
GROUP BY person_id HAVING
event_date >= toDateTime(%(reference_start_date)s) AND event_date <= toDateTime(%(reference_end_date)s)
"""


RETENTION_PEOPLE_SQL = """
SELECT DISTINCT person_id
FROM events e join ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi on e.distinct_id = pdi.distinct_id
where toDateTime(e.timestamp) >= toDateTime(%(start_date)s) AND toDateTime(e.timestamp) <= toDateTime(%(end_date)s)
AND e.team_id = %(team_id)s AND person_id IN (
    SELECT person_id FROM ({reference_event_query}) as persons
) {target_query} {filters}
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
        count(DISTINCT target_event.target) as count
    FROM ({reference_event_sql}) AS target_event

    GROUP BY breakdown_values
    ORDER BY count DESC

    LIMIT %(limit)s
"""
