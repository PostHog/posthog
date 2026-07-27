"""CH insert helpers for surfacing_scoring_sweep integration tests.

Partial inserts into writable_session_replay_events fail on argMin LC/String
type mismatches — use sharded_session_replay_events with argMinState instead.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from posthog.clickhouse.client import sync_execute

_INSERT_SESSION_REPLAY_EVENT_NOW_SQL = """
INSERT INTO sharded_session_replay_events (
    session_id,
    team_id,
    distinct_id,
    min_first_timestamp,
    max_last_timestamp,
    first_url,
    snapshot_source,
    snapshot_library,
    event_count,
    surfacing_score
)
SELECT
    %(session_id)s,
    %(team_id)s,
    %(distinct_id)s,
    now64(6) - INTERVAL 1 HOUR,
    now64(6),
    argMinState(cast(NULL, 'Nullable(String)'), now64(6) - INTERVAL 1 HOUR),
    argMinState(cast(NULL, 'LowCardinality(Nullable(String))'), now64(6) - INTERVAL 1 HOUR),
    argMinState(cast(NULL, 'Nullable(String)'), now64(6) - INTERVAL 1 HOUR),
    %(event_count)s,
    %(surfacing_score)s
"""

_INSERT_SESSION_REPLAY_EVENT_AT_SQL = """
INSERT INTO sharded_session_replay_events (
    session_id,
    team_id,
    distinct_id,
    min_first_timestamp,
    max_last_timestamp,
    first_url,
    snapshot_source,
    snapshot_library,
    event_count,
    surfacing_score
)
SELECT
    %(session_id)s,
    %(team_id)s,
    %(distinct_id)s,
    toDateTime64(%(start)s, 6, 'UTC'),
    toDateTime64(%(end)s, 6, 'UTC'),
    argMinState(cast(NULL, 'Nullable(String)'), toDateTime64(%(start)s, 6, 'UTC')),
    argMinState(cast(NULL, 'LowCardinality(Nullable(String))'), toDateTime64(%(start)s, 6, 'UTC')),
    argMinState(cast(NULL, 'Nullable(String)'), toDateTime64(%(start)s, 6, 'UTC')),
    %(event_count)s,
    %(surfacing_score)s
"""


def insert_session_replay_event(
    *,
    team_id: int,
    session_id: str,
    distinct_id: str = "d1",
    start: datetime | None = None,
    end: datetime | None = None,
    event_count: int = 1,
    surfacing_score: float | None = None,
) -> None:
    params = {
        "session_id": session_id,
        "team_id": team_id,
        "distinct_id": distinct_id,
        "event_count": event_count,
        "surfacing_score": surfacing_score,
    }
    if start is None:
        sync_execute(_INSERT_SESSION_REPLAY_EVENT_NOW_SQL, params)
        return

    at_params: dict[str, Any] = {
        **params,
        "start": start,
        "end": end or start,
    }
    sync_execute(_INSERT_SESSION_REPLAY_EVENT_AT_SQL, at_params)


def insert_replay_features(
    *,
    team_id: int,
    session_id: str,
    distinct_id: str = "d1",
    event_count: int = 42,
) -> None:
    sync_execute(
        "INSERT INTO writable_session_replay_features "
        "(session_id, team_id, distinct_id, min_first_timestamp, max_last_timestamp, event_count) "
        "SELECT %(session_id)s, %(team_id)s, %(distinct_id)s, "
        "now64(6) - INTERVAL 1 HOUR, now64(6), %(event_count)s",
        {
            "session_id": session_id,
            "team_id": team_id,
            "distinct_id": distinct_id,
            "event_count": event_count,
        },
    )
