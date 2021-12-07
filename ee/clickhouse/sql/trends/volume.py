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
    COUNT(DISTINCT id) AS data, -- make sure to not double count actors since person ids will be aligned with distinct ids after distinct is called in the inner query
    date
FROM (
    SELECT
        person_id as id,
        events.date AS date
    FROM ({GET_TEAM_PERSON_DISTINCT_IDS}) AS pdi
    INNER JOIN (
        SELECT
            distinct_id,
            toDateTime({trunc_func}(timestamp), 'UTC') AS date
        FROM events e
            WHERE
            team_id = %(team_id)s 
            {entity_filter}
            {date_filter}
            {prop_filter}
        GROUP BY distinct_id, toDateTime({trunc_func}(timestamp), 'UTC') AS date
    ) AS events 
    ON events.distinct_id = pdi.distinct_id
) GROUP BY date
"""
