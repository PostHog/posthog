# Would love a clickhouse CTE right about here

RETENTION_SQL = """
SELECT
    datediff('day', toDate(%(start_date)s), first_date) as first_date,
    datediff('day', first_event_date.first_date, toDate(timestamp)) as date,
    COUNT(DISTINCT events.person_id) count
FROM (
    SELECT *
    from events e join person_distinct_id pdi on e.distinct_id = pdi.distinct_id
    where toDate(e.timestamp) >= toDate(%(start_date)s) AND toDate(e.timestamp) <= toDate(%(end_date)s)
    AND e.team_id = %(team_id)s
) events
JOIN (
    SELECT DISTINCT 
    pdi.person_id as person_id,
    toStartOfDay(e.timestamp) as first_date
    from events e join person_distinct_id pdi on e.distinct_id = pdi.distinct_id
    where toDate(e.timestamp) >= toDate(%(start_date)s) AND toDate(e.timestamp) <= toDate(%(end_date)s)
    AND e.team_id = %(team_id)s
) first_event_date
    ON (events.person_id = first_event_date.person_id)
WHERE toStartOfDay(timestamp) >= first_event_date.first_date
GROUP BY date, first_date
order by date, first_date
"""
