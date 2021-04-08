VOLUME_SQL = """
SELECT {aggregate_operation} as data, toDateTime({interval}({timestamp}), 'UTC') as date from events {event_join} where team_id = %(team_id)s {entity_query} {filters} {parsed_date_from} {parsed_date_to} GROUP BY {interval}({timestamp})
"""

VOLUME_TOTAL_AGGREGATE_SQL = """
SELECT {aggregate_operation} as data from events {event_join} where team_id = %(team_id)s {entity_query} {filters} {parsed_date_from} {parsed_date_to}
"""

ACTIVE_USER_SQL = """
SELECT 
groupArray(day) as date,
groupArray(counts) as data
FROM (
    SELECT * FROM (
        SELECT d.day, COUNT(DISTINCT person_id) counts FROM (
            SELECT toStartOfDay(timestamp) as day FROM events WHERE team_id = %(team_id)s {parsed_date_from_prev_range} {parsed_date_to} GROUP BY day 
        ) d
        CROSS JOIN (
            SELECT toStartOfDay(timestamp) as day, person_id FROM events INNER JOIN (
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
            WHERE team_id = %(team_id)s {entity_query} {filters} {parsed_date_from_prev_range} {parsed_date_to} GROUP BY day, person_id
        ) e WHERE e.day <= d.day AND e.day > d.day - INTERVAL {interval}
        GROUP BY d.day
        ORDER BY d.day
    ) WHERE {parsed_date_from} {parsed_date_to}
)
"""
