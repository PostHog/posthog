from django.conf import settings

EVENTS_DATA_TABLE = lambda: "sharded_events" if settings.CLICKHOUSE_REPLICATION else "events"

GET_EARLIEST_TIMESTAMP_SQL = """
SELECT timestamp from events WHERE team_id = %(team_id)s AND timestamp > %(earliest_timestamp)s order by toDate(timestamp), timestamp limit 1
"""

GET_EVENTS_BY_TEAM_SQL = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    created_at
FROM events WHERE team_id = %(team_id)s
"""


INSERT_EVENT_SQL = (
    lambda: f"""
INSERT INTO {EVENTS_DATA_TABLE()} (uuid, event, properties, timestamp, team_id, distinct_id, elements_chain, created_at, _timestamp, _offset)
SELECT %(uuid)s, %(event)s, %(properties)s, %(timestamp)s, %(team_id)s, %(distinct_id)s, %(elements_chain)s, %(created_at)s, now(), 0
"""
)
