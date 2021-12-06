VOLUME_SQL = """
SELECT {aggregate_operation} as data, toDateTime({interval}(timestamp), 'UTC') as date FROM ({event_query}) GROUP BY {interval}(timestamp)
"""

VOLUME_TOTAL_AGGREGATE_SQL = """
SELECT {aggregate_operation} as data FROM ({event_query}) events
"""

ACTIVE_USER_SQL = """
SELECT counts as total, timestamp as day_start FROM (
    SELECT d.timestamp, COUNT(DISTINCT person_id) counts FROM (
        SELECT toStartOfDay(timestamp) as timestamp FROM events WHERE team_id = %(team_id)s {parsed_date_from_prev_range} {parsed_date_to} GROUP BY timestamp 
    ) d
    CROSS JOIN (
        SELECT toStartOfDay(timestamp) as timestamp, person_id FROM ({event_query}) events WHERE 1 = 1 {parsed_date_from_prev_range} {parsed_date_to} GROUP BY timestamp, person_id
    ) e WHERE e.timestamp <= d.timestamp AND e.timestamp > d.timestamp - INTERVAL {prev_interval}
    GROUP BY d.timestamp
    ORDER BY d.timestamp
) WHERE 1 = 1 {parsed_date_from} {parsed_date_to}
"""

PERSONS_ACTIVE_USER_SQL = """
SELECT DISTINCT person_id FROM (
    SELECT d.timestamp, person_id FROM (
        SELECT toStartOfDay(timestamp) as timestamp FROM events WHERE team_id = %(team_id)s {parsed_date_from_prev_range} {parsed_date_to} GROUP BY timestamp
    ) d
    CROSS JOIN (
        SELECT toStartOfDay(timestamp) as timestamp, person_id FROM events INNER JOIN (
            {GET_TEAM_PERSON_DISTINCT_IDS}
        ) AS pdi
        ON events.distinct_id = pdi.distinct_id
        WHERE team_id = %(team_id)s {entity_query} {filters} {parsed_date_from_prev_range} {parsed_date_to} GROUP BY timestamp, person_id
    ) e WHERE e.timestamp <= d.timestamp AND e.timestamp > d.timestamp - INTERVAL {prev_interval}
) WHERE 1 = 1 {parsed_date_from} {parsed_date_to}
"""

AGGREGATE_SQL = """
SELECT groupArray(day_start) as date, groupArray(count) as data FROM (
    SELECT SUM(total) AS count, day_start from ({null_sql} UNION ALL {content_sql}) group by day_start order by day_start
)
"""

CUMULATIVE_SQL = """
SELECT person_id, min(timestamp) as timestamp
FROM ({event_query}) GROUP BY person_id
"""


DAU_SQL = """
SELECT 
    COUNT(id) AS data,
    date
FROM (
    SELECT 
        id,
        date
    FROM person 
    INNER JOIN (
        SELECT
            person_id,
            events.date AS date
        FROM (
            SELECT 
                distinct_id,
                argMax(person_id, _timestamp) AS person_id 
            FROM person_distinct_id
            WHERE team_id = %(team_id)s
            GROUP BY distinct_id
            HAVING max(is_deleted) = 0
        ) AS pdi
        INNER JOIN (
            SELECT
                DISTINCT distinct_id,
                toDateTime({trunc_func}(timestamp), 'UTC') AS date
            FROM events
                WHERE
                team_id = %(team_id)s 
                {entity_filter}
                {date_filter}
                {prop_filter}
                group by distinct_id, toDateTime({trunc_func}(timestamp), 'UTC') AS date
        ) AS events 
        ON events.distinct_id = pdi.distinct_id
    ) AS persons_for_event 
    ON person.id = persons_for_event.person_id
    WHERE 
        team_id = %(team_id)s
    GROUP BY id, date
    HAVING max(is_deleted) = 0
) GROUP BY date
"""
