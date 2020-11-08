ACTION_QUERY = """
SELECT
    events.uuid,
    events.event,
    events.properties,
    events.timestamp,
    events.team_id,
    events.distinct_id,
    events.elements_chain,
    events.created_at
FROM events
WHERE {action_filter}
AND events.team_id = %(team_id)s
ORDER BY events.timestamp DESC
"""
