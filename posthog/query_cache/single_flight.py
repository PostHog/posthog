import time
import uuid
import threading
from datetime import datetime
from typing import Literal, Optional

import structlog
from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen
from posthog.query_cache import storage
from posthog.query_cache.failures import Budget

logger = structlog.get_logger(__name__)

QUERY_SINGLE_FLIGHT_FLAG = "query-single-flight"

QUERY_SINGLE_FLIGHT_COUNTER = Counter(
    "posthog_query_single_flight_total",
    "Blocking query executions by their role in a single flight",
    labelnames=["action"],
)

QUERY_SINGLE_FLIGHT_WAIT_SECONDS = Histogram(
    "posthog_query_single_flight_wait_seconds",
    "Time a follower spent waiting for the leader of an identical blocking query",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 60],
)

# The leader extends the lock on every heartbeat, so the lock lives for as long as the leader
# does, and a leader that dies without releasing is noticed within three missed heartbeats.
FLIGHT_HEARTBEAT_INTERVAL = 5.0
FLIGHT_LOCK_TTL = 3 * FLIGHT_HEARTBEAT_INTERVAL
FLIGHT_WAIT_SECONDS = 65
FLIGHT_POLL_INTERVAL = 0.25
# Followers poll every FLIGHT_POLL_INTERVAL, so the published result only has to outlive a few polls.
FLIGHT_RESULT_TTL = 5

# Acquiring the lock also drops the result the previous leader published, so a result can only ever
# belong to the flight that is currently in progress or just ended.
_ACQUIRE_LOCK_SCRIPT = """
if redis.call("set", KEYS[1], ARGV[1], "NX", "PX", ARGV[2]) then
    redis.call("del", KEYS[2])
    return 1
end
return 0
"""

# Every other script acts only while this leader still owns the lock, so a leader that lost the
# lock cannot extend, release, or publish over the leader that replaced it.
_EXTEND_OWN_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("pexpire", KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_OWN_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""

_PUBLISH_RESULT_AND_RELEASE_OWN_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    redis.call("set", KEYS[2], ARGV[2], "EX", ARGV[3])
    return redis.call("del", KEYS[1])
end
return 0
"""

FlightOutcome = Literal["done", "released", "timeout"]


@frozen
class FlightWait:
    outcome: FlightOutcome
    # last_refresh of the entry the leader wrote, present only when the outcome is "done".
    last_refresh: Optional[datetime] = None


class QuerySingleFlight:
    """Collapses concurrent blocking executions of one cache key onto one leader.

    Followers wait for the leader, then serve the cache entry it published or run the query
    themselves. Failures are never transported: repeated failures are the circuit breaker's
    concern. Storage errors fail open to independent execution, never to a query failure.
    """

    def __init__(self, cache_key: str) -> None:
        # The hash tag keeps both keys in one Redis Cluster slot so one script can touch both.
        self.lock_key = f"query_flight:{{{cache_key}}}"
        self.result_key = f"query_flight_result:{{{cache_key}}}"
        self._token = uuid.uuid4().hex
        self._lock_value: Optional[str] = None
        self._heartbeat: Optional[_Heartbeat] = None

    def acquire(self, *, budget: Budget) -> bool:
        """Take the lead, advertising the execution budget this run holds."""
        self._lock_value = f"{self._token}:{budget}"
        try:
            client = storage.query_cache_raw_client()
            # redis-py's stubs omit register_script on RedisCluster; the runtime supports it.
            acquired = client.register_script(_ACQUIRE_LOCK_SCRIPT)(  # type: ignore[union-attr]
                keys=[self.lock_key, self.result_key], args=[self._lock_value, _millis(FLIGHT_LOCK_TTL)]
            )
        except Exception:
            self._storage_failed("acquire")
            return True
        if not acquired:
            return False
        self._heartbeat = _Heartbeat(self)
        return True

    def leader_budget(self) -> Optional[str]:
        """The budget the current leader advertised, or None when there is no leader to read."""
        try:
            value = storage.query_cache_raw_client().get(self.lock_key)
        except Exception:
            self._storage_failed("leader_budget")
            return None
        if value is None:
            return None
        raw = value.decode() if isinstance(value, bytes) else str(value)
        _, _, budget = raw.partition(":")
        return budget or None

    def extend(self) -> bool:
        """Push the lock's expiry out by one TTL. False once this leader no longer owns the lock."""
        try:
            client = storage.query_cache_raw_client()
            extended = client.register_script(_EXTEND_OWN_LOCK_SCRIPT)(  # type: ignore[union-attr]
                keys=[self.lock_key], args=[self._lock_value, _millis(FLIGHT_LOCK_TTL)]
            )
            return bool(extended)
        except Exception:
            self._storage_failed("extend")
            return False

    def release(self, *, last_refresh: Optional[datetime] = None) -> None:
        """Release the lock, publishing which entry the leader wrote when it has one to publish."""
        if self._heartbeat is not None:
            self._heartbeat.stop()
            self._heartbeat = None
        try:
            client = storage.query_cache_raw_client()
            if last_refresh is None:
                client.register_script(_RELEASE_OWN_LOCK_SCRIPT)(keys=[self.lock_key], args=[self._lock_value])  # type: ignore[union-attr]
            else:
                client.register_script(_PUBLISH_RESULT_AND_RELEASE_OWN_LOCK_SCRIPT)(  # type: ignore[union-attr]
                    keys=[self.lock_key, self.result_key],
                    args=[self._lock_value, last_refresh.isoformat(), FLIGHT_RESULT_TTL],
                )
        except Exception:
            self._storage_failed("release")

    def wait(self, timeout_seconds: float) -> FlightWait:
        """Poll until the leader releases the lock, the lock expires, or the timeout elapses."""
        start = time.monotonic()
        deadline = start + timeout_seconds
        result = FlightWait(outcome="timeout")
        while True:
            if not self._in_flight():
                result = self._published_result()
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(FLIGHT_POLL_INTERVAL, remaining))
        QUERY_SINGLE_FLIGHT_WAIT_SECONDS.observe(time.monotonic() - start)
        return result

    def _in_flight(self) -> bool:
        try:
            return bool(storage.query_cache_raw_client().exists(self.lock_key))
        except Exception:
            self._storage_failed("poll")
            return False

    def _published_result(self) -> FlightWait:
        try:
            value = storage.query_cache_raw_client().get(self.result_key)
            if value is None:
                return FlightWait(outcome="released")
            raw = value.decode() if isinstance(value, bytes) else str(value)
            return FlightWait(outcome="done", last_refresh=datetime.fromisoformat(raw))
        except Exception:
            self._storage_failed("published_result")
            return FlightWait(outcome="released")

    def _storage_failed(self, operation: str) -> None:
        # A warning without a traceback: a Redis outage would otherwise log one per blocking query.
        logger.warning("query_single_flight_storage_error", operation=operation, key=self.lock_key)
        QUERY_SINGLE_FLIGHT_COUNTER.labels(action="storage_error").inc()


class _Heartbeat:
    """Extends the leader's lock every FLIGHT_HEARTBEAT_INTERVAL until stopped or until the lock
    is no longer the leader's. A daemon thread, so a dying process takes it down and the lock
    expires on its own."""

    def __init__(self, flight: QuerySingleFlight) -> None:
        self._flight = flight
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="query-single-flight-heartbeat", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(FLIGHT_HEARTBEAT_INTERVAL):
            if not self._flight.extend():
                break

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=FLIGHT_HEARTBEAT_INTERVAL)


def _millis(seconds: float) -> int:
    return int(seconds * 1000)
