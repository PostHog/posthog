"""ClickHouse queries for ingestion limits monitoring."""


def get_high_volume_distinct_ids_query(time_window_minutes: int) -> str:
    """Get the ClickHouse query to find high-volume event senders.

    Args:
        time_window_minutes: Time window in minutes to look back for events

    Returns:
        SQL query string with parameterized time window
    """
    return f"""
WITH candidates AS (
  SELECT arrayJoin(topK(100)(
           (team_id, distinct_id)
         )) AS k
  FROM posthog.events_recent
  PREWHERE timestamp >= now() - INTERVAL {time_window_minutes} MINUTE
)

SELECT
  e.team_id,
  e.distinct_id,
  count() AS offending_event_count
FROM posthog.events_recent AS e
PREWHERE e.timestamp >= now() - INTERVAL {time_window_minutes} MINUTE
WHERE (e.team_id, e.distinct_id) IN
  (SELECT tupleElement(k, 1), tupleElement(k, 2) FROM candidates)
GROUP BY e.team_id, e.distinct_id
ORDER BY offending_event_count DESC
LIMIT 100

SETTINGS
  max_bytes_before_external_group_by = 1073741824,
  max_bytes_before_external_sort     = 1073741824
"""
