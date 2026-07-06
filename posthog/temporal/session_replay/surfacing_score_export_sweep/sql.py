"""ClickHouse statement for the surfacing-score export sweep."""

SESSION_REPLAY_EVENTS_TABLE = "session_replay_events"


def fetch_scored_sessions_sql(replay_events_table: str = SESSION_REPLAY_EVENTS_TABLE) -> str:
    """One (day, hash bucket) export slice. Bound parameters: %(of_chunks)s,
    %(chunk_id)s, %(team_ids)s, %(day_start)s ('YYYY-MM-DD 00:00:00', UTC).

    The raw-row prefilter prunes on the `min_first_timestamp` ordering key; the
    +1 day buffer covers boundary-straddling rows, and the exact day cut is in
    HAVING on the aggregated min (the score writeback row sits at session start
    +1µs, so it is always in-window).
    """
    return f"""
SELECT
    team_id,
    session_id,
    min(min_first_timestamp) AS started_at,
    max(surfacing_score) AS score
FROM {replay_events_table}
WHERE cityHash64(session_id) %% %(of_chunks)s = %(chunk_id)s
  AND team_id IN %(team_ids)s
  AND min_first_timestamp >= toDateTime(%(day_start)s, 'UTC')
  AND min_first_timestamp < toDateTime(%(day_start)s, 'UTC') + toIntervalDay(2)
GROUP BY team_id, session_id
HAVING score IS NOT NULL
  AND max(is_deleted) = 0
  AND started_at >= toDateTime(%(day_start)s, 'UTC')
  AND started_at < toDateTime(%(day_start)s, 'UTC') + toIntervalDay(1)
ORDER BY team_id, session_id
""".strip()
