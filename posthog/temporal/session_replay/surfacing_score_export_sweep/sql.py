"""ClickHouse statement for the surfacing-score export sweep."""

SESSION_REPLAY_EVENTS_TABLE = "session_replay_events"

# Name of the query-scoped external data table that carries the AI-training
# opted-in team ids. The list is sent alongside the request (see
# `sync_execute(external_tables=...)`) instead of inlined into the SQL text, so
# the rendered query stays small no matter how many teams are opted in — the
# whole point is to keep the unbounded list out of ClickHouse's `max_query_size`.
OPTED_IN_TEAMS_EXTERNAL_TABLE = "__ph_opted_in_teams"

# ClickHouse structure of the external table above; `team_id` matches the
# `session_replay_events.team_id` Int64 column.
OPTED_IN_TEAMS_EXTERNAL_STRUCTURE: list[tuple[str, str]] = [("team_id", "Int64")]


def fetch_scored_sessions_page_sql(replay_events_table: str = SESSION_REPLAY_EVENTS_TABLE) -> str:
    """One keyset-paginated page of a (day, hash bucket) export slice.
    Bound parameters: %(of_chunks)s, %(chunk_id)s,
    %(day_start)s ('YYYY-MM-DD 00:00:00', UTC), %(cursor_session_id)s,
    %(cursor_team_id)s, %(page_size)s.

    The opted-in team-id filter reads from the `__ph_opted_in_teams` external
    data table sent with the request, never inlined — the list is unbounded and
    would otherwise blow past ClickHouse's `max_query_size`. Both references use
    `GLOBAL IN` so the initiator resolves the external table (which only lives on
    the initiator) and broadcasts the ids to every shard of the distributed
    `session_replay_events` table.

    The cursor predicate and ORDER BY use the same (session_id, team_id) tuple,
    so pages tile the partition exactly; a page shorter than page_size means
    the slice is exhausted. The raw-row prefilter prunes on the
    `min_first_timestamp` ordering key; the +1 day buffer covers
    boundary-straddling rows, and the exact day cut is in HAVING on the
    aggregated min (the score writeback row sits at session start +1µs, so it
    is always in-window).

    Deletion markers are timestamped at deletion time, not session start, so
    the day-window scan can't see them; the GLOBAL NOT IN subquery matches
    them from the session's day onward with no upper bound. GLOBAL because
    markers are written with an empty distinct_id and can shard away from
    the session's rows.
    """
    return f"""
SELECT
    team_id,
    session_id,
    min(min_first_timestamp) AS started_at,
    max(surfacing_score) AS score
FROM {replay_events_table}
WHERE cityHash64(session_id) %% %(of_chunks)s = %(chunk_id)s
  AND team_id GLOBAL IN (SELECT team_id FROM {OPTED_IN_TEAMS_EXTERNAL_TABLE})
  AND (session_id, team_id) > (%(cursor_session_id)s, %(cursor_team_id)s)
  AND min_first_timestamp >= toDateTime(%(day_start)s, 'UTC')
  AND min_first_timestamp < toDateTime(%(day_start)s, 'UTC') + toIntervalDay(2)
  AND (team_id, session_id) GLOBAL NOT IN (
    SELECT team_id, session_id
    FROM {replay_events_table}
    WHERE cityHash64(session_id) %% %(of_chunks)s = %(chunk_id)s
      AND team_id GLOBAL IN (SELECT team_id FROM {OPTED_IN_TEAMS_EXTERNAL_TABLE})
      AND min_first_timestamp >= toDateTime(%(day_start)s, 'UTC')
      AND is_deleted = 1
  )
GROUP BY team_id, session_id
HAVING score IS NOT NULL
  AND started_at >= toDateTime(%(day_start)s, 'UTC')
  AND started_at < toDateTime(%(day_start)s, 'UTC') + toIntervalDay(1)
ORDER BY session_id, team_id
LIMIT %(page_size)s
""".strip()
