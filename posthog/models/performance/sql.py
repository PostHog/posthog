"""https://developer.mozilla.org/en-US/docs/Web/API/PerformanceEntry"""

from posthog import settings

"""
# expected queries

## get all performance events for a given team's session

allows us to show performance events alongside other logs while viewing a session recording

shard by session id so that when querying for all in session or pageview all data for the results are on the same shard

SELECT * FROM performance_events
WHERE team_id = 1
AND session_id = 'my-session-uuid'
AND timestamp >= {before-the-session}
AND timestamp < now()
ORDER BY timestamp

## get all performance events for a given team's pageview

allows us to show performance events in a waterfall chart for a given pageview

SELECT * FROM performance_events
WHERE team_id = 1
AND session_id = 'my-session-uuid'
AND pageview_id = 'my-page-view-uuid' -- sent by SDK
AND timestamp >= {before-the-session}
AND timestamp < now()
ORDER BY timestamp

## all other queries are expected to be based on aggregating materialized views built from this fact table
"""


def PERFORMANCE_EVENT_DATA_TABLE():
    return "sharded_performance_events"


def UPDATE_PERFORMANCE_EVENTS_TABLE_TTL_SQL():
    return f"ALTER TABLE {PERFORMANCE_EVENT_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' MODIFY TTL toDate(timestamp) + toIntervalWeek(%(weeks)s)"
