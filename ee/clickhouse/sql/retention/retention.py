RETENTION_SQL = """
SELECT
    datediff(%(period)s, {trunc_func}(toDateTime(%(start_date)s)), reference_event.event_date) as base_interval,
    datediff(%(period)s, reference_event.event_date, {trunc_func}(toDateTime(event_date))) as intervals_from_base,
    COUNT(DISTINCT event.person_id) count
FROM (
    SELECT 
    timestamp AS event_date,
    pdi.person_id as person_id,
    e.uuid as uuid,
    e.event as event
    FROM events e join (SELECT person_id, distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s) pdi on e.distinct_id = pdi.distinct_id
    where toDateTime(e.timestamp) >= toDateTime(%(start_date)s) AND toDateTime(e.timestamp) <= toDateTime(%(end_date)s)
    AND e.team_id = %(team_id)s {returning_query} {filters}
) event
JOIN (
    {reference_event_sql}
) reference_event
    ON (event.person_id = reference_event.person_id)
WHERE {trunc_func}(event.event_date) > {trunc_func}(reference_event.event_date)
GROUP BY base_interval, intervals_from_base
ORDER BY base_interval, intervals_from_base
"""

REFERENCE_EVENT_SQL = """
SELECT DISTINCT 
{trunc_func}(e.timestamp) as event_date,
pdi.person_id as person_id,
e.uuid as uuid,
e.event as event
from events e JOIN (SELECT person_id, distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s) pdi on e.distinct_id = pdi.distinct_id
where toDateTime(e.timestamp) >= toDateTime(%(reference_start_date)s) AND toDateTime(e.timestamp) <= toDateTime(%(reference_end_date)s)
AND e.team_id = %(team_id)s {target_query} {filters}
"""

REFERENCE_EVENT_UNIQUE_SQL = """
SELECT DISTINCT 
min({trunc_func}(e.timestamp)) as event_date,
pdi.person_id as person_id,
argMin(e.uuid, {trunc_func}(e.timestamp)) as min_uuid,
argMin(e.event, {trunc_func}(e.timestamp)) as min_event
from events e JOIN (SELECT person_id, distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s) pdi on e.distinct_id = pdi.distinct_id
WHERE e.team_id = %(team_id)s {target_query} {filters} 
GROUP BY person_id HAVING
event_date >= toDateTime(%(reference_start_date)s) AND event_date <= toDateTime(%(reference_end_date)s)
"""


RETENTION_PEOPLE_SQL = """
SELECT DISTINCT person_id 
FROM events e join (SELECT person_id, distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s) pdi on e.distinct_id = pdi.distinct_id
where toDateTime(e.timestamp) >= toDateTime(%(start_date)s) AND toDateTime(e.timestamp) <= toDateTime(%(end_date)s)
AND e.team_id = %(team_id)s AND person_id IN (
    SELECT person_id FROM ({reference_event_query}) as persons
) {target_query} {filters}
LIMIT 100 OFFSET %(offset)s
"""

INITIAL_INTERVAL_SQL = """
SELECT datediff(%(period)s, toStartOfDay(toDateTime(%(start_date)s)), event_date) event_date,
       count(DISTINCT person_id) FROM (
    {reference_event_sql}
) GROUP BY event_date ORDER BY event_date
"""
