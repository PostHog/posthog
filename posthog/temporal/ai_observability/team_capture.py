"""Emitting AI observability events on behalf of a team, without a Postgres read per event.

Every emitted `$ai_evaluation` / `$ai_tag` event needs the team's `api_token` to call
`capture_internal`. Those emit closures run under `database_sync_to_async(thread_sensitive=False)`,
so each one lands on a fresh executor thread and grabs a pooled Postgres connection for a
single-row read — under pool pressure pgbouncer answers with `query_wait_timeout` instead.
`api_token` is effectively static, so cache it per worker process and only pay for the query
once per team per TTL.
"""

import time
import threading
from datetime import datetime
from typing import Any

from posthog.api.capture import CaptureInternalError, capture_internal
from posthog.models.team import Team

TOKEN_CACHE_TTL_SECONDS = 300
# Backstop so a worker seeing a very large number of teams can't grow the cache unbounded.
_MAX_CACHED_TEAMS = 10_000

_lock = threading.Lock()
_cache: dict[int, tuple[float, str]] = {}


class TeamNotFound(Exception):
    pass


def get_team_api_token(team_id: int) -> str:
    """Return the team's API token, reading Postgres at most once per TTL per worker process."""
    now = time.monotonic()
    with _lock:
        entry = _cache.get(team_id)
        if entry is not None and entry[0] > now:
            return entry[1]

    token = Team.objects.filter(id=team_id).values_list("api_token", flat=True).first()
    if token is None:
        raise TeamNotFound(f"Team {team_id} not found")

    with _lock:
        if len(_cache) >= _MAX_CACHED_TEAMS:
            _cache.clear()
        _cache[team_id] = (time.monotonic() + TOKEN_CACHE_TTL_SECONDS, token)
    return token


def invalidate_team_api_token(team_id: int) -> None:
    """Drop a cached token so the next emit re-reads it — used when capture rejects the token,
    which is how a rotated token recovers before the TTL expires."""
    with _lock:
        _cache.pop(team_id, None)


def clear_team_api_token_cache() -> None:
    with _lock:
        _cache.clear()


def capture_internal_for_team(
    *,
    team_id: int,
    event_name: str,
    event_source: str,
    distinct_id: str,
    timestamp: datetime,
    properties: dict[str, Any],
    process_person_profile: bool = True,
) -> None:
    """Capture one event for a team, raising on a non-2xx capture response."""
    token = get_team_api_token(team_id)
    try:
        result = capture_internal(
            token=token,
            event_name=event_name,
            event_source=event_source,
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties=properties,
            process_person_profile=process_person_profile,
        )
        result.raise_for_status()
    except Exception as e:
        # A team over its quota keeps a valid token, so don't force a re-read on every event.
        if not (isinstance(e, CaptureInternalError) and e.is_billing_limit_exceeded):
            invalidate_team_api_token(team_id)
        raise
