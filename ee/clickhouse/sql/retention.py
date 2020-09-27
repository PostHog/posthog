# Would love a clickhouse CTE right about here

RETENTION_SQL = """
SELECT
    datediff(%(period)s, {trunc_func}(toDate(%(start_date)s)), first_date) as first_date,
    datediff(%(period)s, first_event_date.first_date, {trunc_func}(toDate(timestamp))) as date,
    COUNT(DISTINCT events.person_id) count
FROM (
    SELECT *
    from events e join person_distinct_id pdi on e.distinct_id = pdi.distinct_id
    where toDate(e.timestamp) >= toDate(%(start_date)s) AND toDate(e.timestamp) <= toDate(%(end_date)s)
    AND e.team_id = %(team_id)s {target_query} {filters}
) events
JOIN (
    SELECT DISTINCT 
    pdi.person_id as person_id,
    {trunc_func}(e.timestamp) as first_date
    from events e join person_distinct_id pdi on e.distinct_id = pdi.distinct_id
    where toDate(e.timestamp) >= toDate(%(start_date)s) AND toDate(e.timestamp) <= toDate(%(end_date)s)
    AND e.team_id = %(team_id)s
) first_event_date
    ON (events.person_id = first_event_date.person_id)
WHERE {trunc_func}(timestamp) >= {trunc_func}(first_event_date.first_date)
GROUP BY date, first_date
order by date, first_date
"""
