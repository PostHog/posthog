RETENTION_PEOPLE_PER_PERIOD_SQL = """
SELECT toString(actor_id), count(actor_id) appearance_count, groupArray(intervals_from_base) appearances FROM (
    SELECT DISTINCT
        datediff(%(period)s, {trunc_func}(toDateTime(%(start_date)s)), reference_event.event_date) as base_interval,
        datediff(%(period)s, reference_event.event_date, {trunc_func}(toDateTime(event_date))) as intervals_from_base,
        event.actor_id
    FROM (
        SELECT
        timestamp AS event_date,
        {actor_field_name},
        e.uuid as uuid,
        e.event as event
        FROM events e
        {person_join}
        where toDateTime(e.timestamp) >= toDateTime(%(start_date)s) AND toDateTime(e.timestamp) <= toDateTime(%(end_date)s)
        AND e.team_id = %(team_id)s {returning_query} {filters}
    ) event
    JOIN (
        {first_event_sql}
    ) reference_event
        ON (event.actor_id = reference_event.actor_id)
    WHERE {trunc_func}(event.event_date) > {trunc_func}(reference_event.event_date)
    UNION ALL
    {first_event_default_sql}
) person_appearances
WHERE base_interval = 0
GROUP BY actor_id
ORDER BY appearance_count DESC
LIMIT %(limit)s OFFSET %(offset)s
"""

REFERENCE_EVENT_PEOPLE_PER_PERIOD_SQL = """
SELECT DISTINCT
{trunc_func}(e.timestamp) as event_date,
{actor_field_name},
e.uuid as uuid,
e.event as event
from events e
{person_join}
where event_date = {trunc_func}(toDateTime(%(start_date)s))
AND e.team_id = %(team_id)s {target_query} {filters}
"""


DEFAULT_REFERENCE_EVENT_PEOPLE_PER_PERIOD_SQL = """
SELECT DISTINCT
0,
0,
{actor_field_name}
from events e
{person_join}
where {trunc_func}(e.timestamp) = {trunc_func}(toDateTime(%(start_date)s))
AND e.team_id = %(team_id)s {target_query} {filters}
"""

REFERENCE_EVENT_UNIQUE_PEOPLE_PER_PERIOD_SQL = """
SELECT DISTINCT
min({trunc_func}(e.timestamp)) as event_date,
{actor_field_name},
argMin(e.uuid, {trunc_func}(e.timestamp)) as min_uuid,
argMin(e.event, {trunc_func}(e.timestamp)) as min_event
from events e
{person_join}
WHERE e.team_id = %(team_id)s {target_query} {filters}
GROUP BY actor_id HAVING
event_date = {trunc_func}(toDateTime(%(start_date)s))
"""

DEFAULT_REFERENCE_EVENT_UNIQUE_PEOPLE_PER_PERIOD_SQL = """
SELECT DISTINCT
0,
0,
{actor_field_name}
from events e
{person_join}
WHERE e.team_id = %(team_id)s {target_query} {filters}
GROUP BY actor_id HAVING
min({trunc_func}(e.timestamp)) = {trunc_func}(toDateTime(%(start_date)s))
"""
