import json
import time
import uuid
import threading
from dataclasses import asdict
from datetime import datetime
from typing import Literal, Optional

from django.conf import settings

import structlog
from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen
from posthog.query_cache import storage
from posthog.query_cache.failures import BUDGET_EXTENDED, BUDGET_INTERACTIVE, Budget

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
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600],
)

# The leader extends the lock on every heartbeat, so the lock lives for as long as the leader
# does, and a leader that dies without releasing is noticed within three missed heartbeats.
FLIGHT_HEARTBEAT_INTERVAL = 5.0
FLIGHT_LOCK_TTL = 3 * FLIGHT_HEARTBEAT_INTERVAL
# A follower waits a few seconds past the ClickHouse execution time its budget allows the leader.
FLIGHT_WAIT_SECONDS: dict[Budget, float] = {
    BUDGET_INTERACTIVE: 65.0,
    BUDGET_EXTENDED: settings.HOGQL_INCREASED_MAX_EXECUTION_TIME + 5.0,
}
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

FlightOutcome = Literal["done", "failed", "released", "timeout"]


@frozen
class SharedFailure:
    """A leader's failure in the form a follower rebuilds into the same exception: a ClickHouse
    server error by its code, or an exposed HogQL error by its class name."""

    message: str
    code: Optional[int] = None
    class_name: Optional[str] = None
    start: Optional[int] = None
    end: Optional[int] = None
    fix: Optional[str] = None

    def __post_init__(self) -> None:
        if (self.code is None) == (self.class_name is None):
            raise ValueError("SharedFailure needs exactly one of code or class_name")


@frozen
class FlightWait:
    outcome: FlightOutcome
    # last_refresh of the entry the leader wrote, present only when the outcome is "done".
    last_refresh: Optional[datetime] = None
    # The leader's failure, present when the outcome is "failed" and the failure could be shared.
    failure: Optional[SharedFailure] = None


class QuerySingleFlight:
    """Collapses concurrent blocking executions of one cache key and budget onto one leader.

    Followers wait for the leader, then serve the entry it published or fail the way it published.
    A follower never runs the query. Storage errors fail open to independent execution, never to
    a query failure.
    """

    def __init__(self, cache_key: str, budget: Budget) -> None:
        # The hash tag keeps both keys in one Redis Cluster slot so one script can touch both.
        # Runs of different budgets get different ClickHouse execution time, so they never pair.
        self.lock_key = f"query_flight:{{{cache_key}}}:{budget}"
        self.result_key = f"query_flight_result:{{{cache_key}}}:{budget}"
        self._token = uuid.uuid4().hex
        self._heartbeat: Optional[_Heartbeat] = None

    def acquire(self) -> bool:
        try:
            client = storage.query_cache_raw_client()
            # redis-py's stubs omit register_script on RedisCluster; the runtime supports it.
            acquired = client.register_script(_ACQUIRE_LOCK_SCRIPT)(  # type: ignore[union-attr]
                keys=[self.lock_key, self.result_key], args=[self._token, _millis(FLIGHT_LOCK_TTL)]
            )
        except Exception:
            self._storage_failed("acquire")
            return True
        if not acquired:
            return False
        self._heartbeat = _Heartbeat(self)
        return True

    def extend(self) -> Optional[bool]:
        """Push the lock's expiry out by one TTL. False once this leader no longer owns the lock,
        None when storage was unreachable and ownership is unknown."""
        try:
            client = storage.query_cache_raw_client()
            extended = client.register_script(_EXTEND_OWN_LOCK_SCRIPT)(  # type: ignore[union-attr]
                keys=[self.lock_key], args=[self._token, _millis(FLIGHT_LOCK_TTL)]
            )
            return bool(extended)
        except Exception:
            self._storage_failed("extend")
            return None

    def succeed(self, last_refresh: Optional[datetime]) -> None:
        """Release the lock, telling followers which entry to serve. A result without a
        last_refresh cannot be found again, so it is released without a publication."""
        self._release(None if last_refresh is None else {"last_refresh": last_refresh.isoformat()})

    def fail(self, failure: Optional[SharedFailure]) -> None:
        """Release the lock, telling followers the leader failed, with the failure when it can be shared."""
        self._release({"failure": None if failure is None else asdict(failure)})

    def release(self) -> None:
        """Release the lock without a publication, as if this leader had never run."""
        self._release(None)

    def _release(self, published: Optional[dict]) -> None:
        if self._heartbeat is not None:
            self._heartbeat.stop()
            self._heartbeat = None
        try:
            client = storage.query_cache_raw_client()
            if published is None:
                client.register_script(_RELEASE_OWN_LOCK_SCRIPT)(keys=[self.lock_key], args=[self._token])  # type: ignore[union-attr]
            else:
                client.register_script(_PUBLISH_RESULT_AND_RELEASE_OWN_LOCK_SCRIPT)(  # type: ignore[union-attr]
                    keys=[self.lock_key, self.result_key],
                    args=[self._token, json.dumps(published), FLIGHT_RESULT_TTL],
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
            published = json.loads(value)
            if "failure" in published:
                failure = published["failure"]
                return FlightWait(outcome="failed", failure=None if failure is None else SharedFailure(**failure))
            return FlightWait(outcome="done", last_refresh=datetime.fromisoformat(published["last_refresh"]))
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
            # Keep beating through a storage error: the lock is still ours until it expires, and
            # stopping here would hand the flight to a follower while this leader still runs.
            if self._flight.extend() is False:
                break

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=FLIGHT_HEARTBEAT_INTERVAL)


def _millis(seconds: float) -> int:
    return int(seconds * 1000)
