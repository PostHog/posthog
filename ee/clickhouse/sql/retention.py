# Would love a clickhouse CTE right about here

RETENTION_SQL = """
SELECT
    datediff(%(period)s, {trunc_func}(toDateTime(%(start_date)s)), reference_event.event_date) as period_to_event_days,
    datediff(%(period)s, reference_event.event_date, {trunc_func}(toDateTime(event_date))) as period_between_events_days,
    COUNT(DISTINCT event.distinct_id) count
FROM (
    SELECT 
    timestamp AS event_date,
    distinct_id
    from events e
    where toDateTime(e.timestamp) >= toDateTime(%(start_date)s) AND toDateTime(e.timestamp) <= toDateTime(%(end_date)s)
    AND e.team_id = %(team_id)s {target_query} {filters}
) event
JOIN (
    SELECT DISTINCT 
    distinct_id,
    {trunc_func}(e.timestamp) as event_date
    from events e 
    where toDateTime(e.timestamp) >= toDateTime(%(start_date)s) AND toDateTime(e.timestamp) <= toDateTime(%(end_date)s)
    AND e.team_id = %(team_id)s {target_query} {filters}
) reference_event
    ON (event.distinct_id = reference_event.distinct_id)
WHERE {trunc_func}(event.event_date) >= {trunc_func}(reference_event.event_date)
GROUP BY period_to_event_days, period_between_events_days
ORDER BY period_to_event_days, period_between_events_days
"""
