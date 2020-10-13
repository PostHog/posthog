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
    WHERE toDateTime(e.timestamp) >= toDateTime(%(start_date)s) AND toDateTime(e.timestamp) <= toDateTime(%(end_date)s)
    AND e.team_id = %(team_id)s {target_query} {filters}
) events
JOIN (
    SELECT
    person_id,
        if({trunc_func}(minMerge(first_observation)) >= toDateTime(%(start_date)s), {trunc_func}(minMerge(first_observation)),toDateTime(%(start_date)s)) as first_date
    FROM  person_retention_period e
    WHERE
        team_id = %(team_id)s {target_query} {filters}
    GROUP BY
        person_id
    HAVING toDateTime(maxMerge(last_observation)) >= %(start_date)s
    AND toDateTime(maxMerge(last_observation)) <= %(end_date)s
) first_event_date
    ON (events.person_id = first_event_date.person_id)
WHERE {trunc_func}(events.timestamp) >= {trunc_func}(first_event_date.first_date)
GROUP BY date, first_date
ORDER BY date, first_date
"""


PERSON_RETENTION_PERIOD_MV = """
CREATE MATERIALIZED VIEW person_retention_period
ENGINE = AggregatingMergeTree() ORDER BY (
    person_id,
    team_id,
    event
)
POPULATE
AS SELECT
person_distinct_id.person_id,
team_id,
event,
argMinState(uuid, timestamp) uuid,
minState(timestamp) first_observation,
maxState(timestamp) last_observation
FROM events JOIN person_distinct_id ON events.distinct_id = person_distinct_id.distinct_id
GROUP BY
person_distinct_id.person_id, team_id, event;
"""
