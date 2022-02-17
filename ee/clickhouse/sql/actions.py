ACTION_QUERY = """
SELECT
    events.uuid,
    events.distinct_id
FROM events
WHERE {action_filter}
AND events.team_id = %(team_id)s
ORDER BY events.timestamp DESC
"""
