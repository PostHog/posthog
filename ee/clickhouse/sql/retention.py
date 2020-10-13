# Would love a clickhouse CTE right about here

RETENTION_SQL = """
SELECT
    datediff(%(period)s, {trunc_func}(toDateTime(%(start_date)s)), first_date) as first_date,
    datediff(%(period)s, first_event_date.first_date, {trunc_func}(toDateTime(timestamp))) as date,
    COUNT(DISTINCT events.person_id) count
FROM (
    SELECT 
    timestamp,
    person_id
    from events e join person_distinct_id pdi on e.distinct_id = pdi.distinct_id
    where toDateTime(e.timestamp) >= toDateTime(%(start_date)s) AND toDateTime(e.timestamp) <= toDateTime(%(end_date)s)
    AND e.team_id = %(team_id)s {target_query} {filters}
) events
JOIN (
    SELECT DISTINCT 
    pdi.person_id as person_id,
    {trunc_func}(e.timestamp) as first_date
    from events e join person_distinct_id pdi on e.distinct_id = pdi.distinct_id
    where toDateTime(e.timestamp) >= toDateTime(%(start_date)s) AND toDateTime(e.timestamp) <= toDateTime(%(end_date)s)
    AND e.team_id = %(team_id)s {target_query} {filters}
) first_event_date
    ON (events.person_id = first_event_date.person_id)
WHERE {trunc_func}(timestamp) >= {trunc_func}(first_event_date.first_date)
GROUP BY date, first_date
order by date, first_date
"""
