RETENTION_SQL = """
select first_event, delta as days_on_site, groupArray(person_id) from 
(
    select pdi.person_id
    , toDate(min(e.timestamp)) first_event
    , max(e.timestamp) last_event
    , datediff('day', min(toDateTime(e.timestamp)), max(toDateTime(e.timestamp))) delta
    from events e join person_distinct_id pdi on e.distinct_id = pdi.distinct_id
    where e.timestamp >= toDateTime64('2020-08-01 00:00:00', 6) AND e.timestamp <= toDateTime64('2020-08-11 00:00:00', 6)
    AND e.team_id = %(team_id)s
    group by pdi.person_id
)
group by first_event, delta
order by first_event, delta asc
"""


full_query = """
    SELECT
        DATE_PART('days', first_date - %s) AS first_date,
        DATE_PART('days', timestamp - first_date) AS date,
        COUNT(DISTINCT "events"."person_id"),
        array_agg(DISTINCT "events"."person_id") as people
    FROM ({events_query}) events
    LEFT JOIN ({first_date_query}) first_event_date
        ON (events.person_id = first_event_date.person_id)
    WHERE timestamp > first_date
    GROUP BY date, first_date
"""
