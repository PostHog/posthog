"""One computation per cache key: concurrent blocking runs of one query share one result.

A process about to compute a query claims the cache key in Redis. The claim carries a short
TTL that a background thread in the claiming process keeps extending, so a claim outlives a
dead process by at most CLAIM_TTL_SECONDS. Concurrent runs of the same query wait instead of
computing: the cached result appearing means join it; the claim disappearing means the
computation ended without a cacheable result (an error, or a dead process), so one waiter
claims and computes. Every failure direction degrades to computing the query, the behavior
without deduplication, never to a hang or a stale result.
"""

import time
import uuid
import threading
from collections.abc import Callable
from datetime import timedelta
from enum import StrEnum
from typing import Optional

from django.conf import settings
from django.db import DatabaseError

import structlog
from prometheus_client import Counter, Histogram

from posthog.cache_utils import cache_for
from posthog.dataclasses import frozen
from posthog.query_cache import storage
from posthog.query_cache.results import fetch_entry_freshness

logger = structlog.get_logger(__name__)

# The TTL bounds how long a dead process's claim can make waiters hold on; the refresh
# interval keeps a live claim from expiring even when several refresh cycles are missed.
CLAIM_TTL_SECONDS = 30
CLAIM_REFRESH_INTERVAL_SECONDS = 5
WAIT_POLL_INTERVAL_SECONDS = 0.3

_CLAIM_KEY_PREFIX = "posthog:query_claim:"

DEDUP_WAIT_COUNTER = Counter(
    "posthog_query_dedup_wait_total",
    "Blocking query runs that found another run computing the same cache key, by wait outcome.",
    labelnames=["outcome"],
)

DEDUP_WAIT_DURATION = Histogram(
    "posthog_query_dedup_wait_seconds",
    "Time spent waiting on another run's computation, by wait outcome.",
    labelnames=["outcome"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, float("inf")],
)

# Extends a claim's TTL only while it still holds the refresher's run id, so a refresh cycle
# that raced a takeover cannot revive a claim that now belongs to another run.
_EXTEND_IF_OWNED_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
return 0
"""

# Deletes a claim only while it still holds the releaser's run id, so a run whose claim
# expired mid-computation cannot delete the claim of the waiter that took over.
_RELEASE_IF_OWNED_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class WaitOutcome(StrEnum):
    RESULT_READY = "result_ready"
    CLAIM_RELEASED = "claim_released"
    TIMED_OUT = "timed_out"


@frozen
class InflightClaim:
    cache_key: str
    run_id: str


@cache_for(timedelta(seconds=60))
def blocking_dedup_enabled() -> bool:
    from posthog.models.instance_setting import get_instance_setting

    try:
        # An instance setting rather than env so the fleet-wide kill switch applies within a
        # minute, without a rolling restart.
        return bool(get_instance_setting("QUERY_BLOCKING_DEDUP_ENABLED"))
    except DatabaseError:
        # The gate runs on the query hot path and must not add a hard Postgres dependency.
        logger.warning("query_dedup_setting_lookup_failed", exc_info=True)
    return settings.QUERY_BLOCKING_DEDUP_ENABLED


def _claim_redis_key(cache_key: str) -> str:
    return _CLAIM_KEY_PREFIX + cache_key


# The heartbeat thread refreshes every claim this process holds. Claims register on acquire
# and deregister on release, on takeover, and on expiry, so a claim key present here always
# belongs to a computation this process still believes is running. If the process dies the
# thread dies with it and the claims expire by TTL, which is the liveness signal waiters use.
_active_claims: dict[str, str] = {}
_claims_lock = threading.Lock()
_heartbeat_thread: Optional[threading.Thread] = None


def _register_claim(redis_key: str, run_id: str) -> None:
    global _heartbeat_thread
    with _claims_lock:
        _active_claims[redis_key] = run_id
        # Started on first use so the thread lives in the serving process, not in a pre-fork
        # parent whose threads would not survive the fork. is_alive() re-checks because the
        # loop catches broadly but a thread can still die on an error outside its try.
        if _heartbeat_thread is None or not _heartbeat_thread.is_alive():
            _heartbeat_thread = threading.Thread(target=_heartbeat_loop, name="query-dedup-claims", daemon=True)
            _heartbeat_thread.start()


def _deregister_claim(redis_key: str, run_id: str) -> None:
    with _claims_lock:
        if _active_claims.get(redis_key) == run_id:
            del _active_claims[redis_key]


def _heartbeat_loop() -> None:
    while True:
        time.sleep(CLAIM_REFRESH_INTERVAL_SECONDS)
        _refresh_active_claims()


def _refresh_active_claims() -> None:
    with _claims_lock:
        claims = dict(_active_claims)
    if not claims:
        return
    try:
        client = storage.query_cache_raw_client()
        for redis_key, run_id in claims.items():
            # redis-py's stubs omit eval on RedisCluster; the runtime supports it.
            extended = client.eval(_EXTEND_IF_OWNED_SCRIPT, 1, redis_key, run_id, CLAIM_TTL_SECONDS)  # type: ignore[union-attr]
            if not extended:
                # The claim expired or another run took it over; stop refreshing it. The
                # computation still finishes and its release safely no-ops.
                _deregister_claim(redis_key, run_id)
    except Exception:
        # A missed cycle only shortens the claim's remaining TTL. With Redis down long
        # enough the claim expires and a waiter recomputes, which is the safe direction.
        logger.warning("query_dedup_claim_refresh_failed", exc_info=True)


def acquire_claim(cache_key: str) -> Optional[InflightClaim]:
    """Claim the cache key for this process's computation.

    None only when another run verifiably holds the key. With Redis unreachable the claim is
    granted without being stored, so deduplication degrades to every caller computing rather
    than every caller waiting on a claim nobody can hold.
    """
    run_id = uuid.uuid4().hex
    redis_key = _claim_redis_key(cache_key)
    try:
        stored = storage.query_cache_raw_client().set(redis_key, run_id, nx=True, ex=CLAIM_TTL_SECONDS)
    except Exception:
        logger.warning("query_dedup_claim_write_failed", cache_key=cache_key, exc_info=True)
        return InflightClaim(cache_key=cache_key, run_id=run_id)
    if not stored:
        return None
    _register_claim(redis_key, run_id)
    return InflightClaim(cache_key=cache_key, run_id=run_id)


def release_claim(claim: InflightClaim) -> None:
    """Never raises: a claim that fails to release expires by TTL within CLAIM_TTL_SECONDS."""
    redis_key = _claim_redis_key(claim.cache_key)
    _deregister_claim(redis_key, claim.run_id)
    try:
        # redis-py's stubs omit eval on RedisCluster; the runtime supports it.
        storage.query_cache_raw_client().eval(_RELEASE_IF_OWNED_SCRIPT, 1, redis_key, claim.run_id)  # type: ignore[union-attr]
    except Exception:
        logger.warning("query_dedup_claim_release_failed", cache_key=claim.cache_key, exc_info=True)


def _claim_exists(cache_key: str) -> bool:
    try:
        return bool(storage.query_cache_raw_client().exists(_claim_redis_key(cache_key)))
    except Exception:
        # Redis unreachable reads as released so the waiter falls back to computing.
        return False


def wait_for_cached_result(
    cache_key: str,
    team_id: int,
    *,
    deadline: float,
    poll_interval: float = WAIT_POLL_INTERVAL_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> WaitOutcome:
    """Wait for the run holding this cache key's claim to finish.

    RESULT_READY: the cache holds a result stored after this wait began; join it.
    CLAIM_RELEASED: the claim is gone and no new result appeared; try to claim and compute.
    TIMED_OUT: the deadline passed with the claim still held; compute anyway.

    The freshness snapshot is taken here rather than before the caller's claim attempt, so a
    result stored in the gap between the two reads goes undetected and is recomputed. The gap
    is two adjacent Redis calls; the cost of losing that race is one duplicate computation.
    """
    started = monotonic()
    snapshot = fetch_entry_freshness(cache_key, team_id)
    while True:
        current = fetch_entry_freshness(cache_key, team_id)
        # A change to None is eviction, not a result; only a present, different entry joins.
        if current is not None and current != snapshot:
            outcome = WaitOutcome.RESULT_READY
            break
        if not _claim_exists(cache_key):
            # The runner stores its result before releasing, so the release can land between
            # the freshness read above and the claim check; re-read before concluding the
            # computation produced nothing.
            current = fetch_entry_freshness(cache_key, team_id)
            if current is not None and current != snapshot:
                outcome = WaitOutcome.RESULT_READY
            else:
                outcome = WaitOutcome.CLAIM_RELEASED
            break
        if monotonic() >= deadline:
            outcome = WaitOutcome.TIMED_OUT
            break
        sleep(poll_interval)

    DEDUP_WAIT_COUNTER.labels(outcome=outcome.value).inc()
    DEDUP_WAIT_DURATION.labels(outcome=outcome.value).observe(monotonic() - started)
    return outcome
