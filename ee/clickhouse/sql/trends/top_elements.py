TOP_ELEMENTS_ARRAY_OF_KEY_SQL = """
SELECT groupArray(value) FROM (
    SELECT value, count(*) as count 
    FROM 
    events e INNER JOIN
        (
            SELECT *
            FROM events_properties_view AS ep
            WHERE key = %(key)s AND team_id = %(team_id)s
        ) ep ON e.uuid = ep.event_id WHERE team_id = %(team_id)s {parsed_date_from} {parsed_date_to}
    GROUP BY value
    ORDER BY count DESC
    LIMIT %(limit)s
)
"""
