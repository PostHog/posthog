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
            SELECT person_id,
                distinct_id
            FROM (
                    SELECT *
                    FROM person_distinct_id
                    JOIN (
                            SELECT distinct_id,
                                max(_offset) as _offset
                            FROM person_distinct_id
                            WHERE team_id = %(team_id)s
                            GROUP BY distinct_id
                        ) as person_max
                        ON person_distinct_id.distinct_id = person_max.distinct_id
                    AND person_distinct_id._offset = person_max._offset
                    WHERE team_id = %(team_id)s
                )
            WHERE team_id = %(team_id)s
        ) as pid
        ON events.distinct_id = pid.distinct_id
        WHERE team_id = %(team_id)s {entity_query} {filters} {parsed_date_from_prev_range} {parsed_date_to} GROUP BY timestamp, person_id
    ) e WHERE e.timestamp <= d.timestamp AND e.timestamp > d.timestamp - INTERVAL {prev_interval}
) WHERE 1 = 1 {parsed_date_from} {parsed_date_to}
"""
