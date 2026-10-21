"""Emitting AI observability events on behalf of a team, without a Postgres read per event.

Every emitted `$ai_evaluation` / `$ai_tag` event needs the team's `api_token` to call
`capture_ai_internal`. Those emit closures run under `database_sync_to_async(thread_sensitive=False)`,
so each one lands on a fresh executor thread and grabs a pooled Postgres connection for a
single-row read — under pool pressure pgbouncer answers with `query_wait_timeout` instead.
`api_token` is effectively static, so cache it per worker process and only pay for the query
once per team per TTL.
"""

import time
import threading
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any, NoReturn

from temporalio.common import RetryPolicy

from posthog.api.capture import CaptureInternalError, capture_ai_internal
from posthog.models.team import Team
from posthog.temporal.ai_observability.retries import is_last_attempt
from posthog.temporal.common.errors import NonReportableApplicationError

# Also bounds how long emits keep using a rotated token: capture-rs accepts stale tokens at
# the edge, so rotation is only picked up once this TTL lapses.
TOKEN_CACHE_TTL_SECONDS = 300
# Backstop so a worker seeing a very large number of teams can't grow the cache unbounded.
_MAX_CACHED_TEAMS = 10_000

_AUTH_REJECTED_STATUSES = (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN)

# A capture-ai restart or DNS blip outlasts the urllib3 retries inside capture_ai_internal. The
# attempts wait 5s, 10s, 20s and 40s between them, so the last one starts over a minute after the first.
EMIT_EVENT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_attempts=5,
)
# Each schedule_to_close budget fits every attempt running to its start_to_close timeout plus the
# backoff, so the attempt count ends retries and `raise_emit_failure` can tell the final attempt.
EMIT_EVENT_START_TO_CLOSE_TIMEOUT = timedelta(seconds=30)
EMIT_EVENT_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(minutes=4)
# For emits that first read their generation, which can run to several MiB.
HYDRATING_EMIT_START_TO_CLOSE_TIMEOUT = timedelta(seconds=120)
HYDRATING_EMIT_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(minutes=12)

_lock = threading.Lock()
_cache: dict[int, tuple[float, str]] = {}


class TeamNotFound(Exception):
    pass


def raise_emit_failure(error: Exception) -> NoReturn:
    """Re-raise an emit failure, kept out of error tracking while Temporal still has attempts left."""
    if is_last_attempt():
        raise error
    raise NonReportableApplicationError(str(error), type=type(error).__name__) from error


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


def capture_ai_internal_for_team(
    *,
    team_id: int,
    event_name: str,
    event_source: str,
    distinct_id: str,
    timestamp: datetime,
    properties: dict[str, Any],
    process_person_profile: bool = True,
    event_uuid: str | None = None,
) -> None:
    """Capture one AI event for a team, raising on a non-2xx capture response.

    Every caller here emits `$ai_*` events, so this goes to the AI lane
    (`/i/v1/ai/events` on capture-ai). A non-AI event name would be rerouted to the
    analytics lane and counted, not rejected.
    """
    token = get_team_api_token(team_id)
    try:
        result = capture_ai_internal(
            token=token,
            event_name=event_name,
            event_source=event_source,
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties=properties,
            process_person_profile=process_person_profile,
            event_uuid=event_uuid,
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
