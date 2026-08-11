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
from http import HTTPStatus
from typing import Any

from posthog.api.capture import CaptureInternalError, capture_internal
from posthog.models.team import Team

# Also bounds how long emits keep using a rotated token: capture-rs accepts stale tokens at
# the edge, so rotation is only picked up once this TTL lapses.
TOKEN_CACHE_TTL_SECONDS = 300
# Backstop so a worker seeing a very large number of teams can't grow the cache unbounded.
_MAX_CACHED_TEAMS = 10_000

_AUTH_REJECTED_STATUSES = (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN)

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
            # Evict the half closest to expiry rather than clearing, so a full cache doesn't
            # send every team back to Postgres at once.
            for evicted_id in sorted(_cache, key=lambda cached_id: _cache[cached_id][0])[: _MAX_CACHED_TEAMS // 2]:
                del _cache[evicted_id]
        _cache[team_id] = (time.monotonic() + TOKEN_CACHE_TTL_SECONDS, token)
    return token


def invalidate_team_api_token(team_id: int) -> None:
    """Drop a cached token so the next emit re-reads it from Postgres."""
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
    except CaptureInternalError as e:
        # Only an explicit auth rejection means the cached token is stale. Timeouts, 5xx, and
        # billing-limit 402s say nothing about the token, and invalidating on them would
        # reintroduce the per-event Postgres read exactly while capture is unhealthy.
        # capture-rs doesn't verify tokens against Postgres at the edge yet, so until it does,
        # a rotated token recovers via the TTL rather than through this branch.
        if e.status_code in _AUTH_REJECTED_STATUSES:
            invalidate_team_api_token(team_id)
        raise
