import json
import time
import uuid
import threading
from dataclasses import asdict, fields
from datetime import datetime
from typing import Any, Literal, Optional

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
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1800, 3600],
)

# The leader extends the lock on every heartbeat, so the lock lives for as long as the leader
# does, and a leader that dies without releasing is noticed within three missed heartbeats.
FLIGHT_HEARTBEAT_INTERVAL = 5.0
FLIGHT_LOCK_TTL = 3 * FLIGHT_HEARTBEAT_INTERVAL
# The longest a leader holds its lock. Past it the heartbeat stops and the lock expires, so a leader
# stuck in its query cannot hold a cache key for as long as its process lives. Followers wait while
# the lock exists, so this also bounds their wait. It covers limiter queueing and runners that send
# several queries, not only one ClickHouse execution.
FLIGHT_MAX_LEADER_SECONDS: dict[Budget, float] = {
    BUDGET_INTERACTIVE: 300.0,
    BUDGET_EXTENDED: 3600.0,
}
# Followers poll quickly at first and then back off, so a follower of a long leader costs little.
FLIGHT_POLL_INTERVAL = 0.25
FLIGHT_MAX_POLL_INTERVAL = 1.0
# Acquiring the lock drops the previous result, so the result can safely outlive a stalled follower.
FLIGHT_RESULT_TTL = 60

# Acquiring the lock also drops the result the previous leader published, so a result can only ever
# belong to the flight that is currently in progress or just ended.
_ACQUIRE_LOCK_SCRIPT = """
if redis.call("set", KEYS[1], ARGV[1], "NX", "PX", ARGV[2]) then
    redis.call("del", KEYS[2])
    return 1
end
return 0
"""

# Every other leader script acts only while this leader still owns the lock, so a leader that lost
# the lock cannot extend, release, or publish over the leader that replaced it.
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

# Reads the lock and the result in one step, so a new leader cannot drop the result between two reads.
_POLL_SCRIPT = """
if redis.call("exists", KEYS[1]) == 1 then
    return {1}
end
return {0, redis.call("get", KEYS[2]) or ""}
"""

FlightOutcome = Literal["done", "failed", "released", "timeout", "unavailable"]


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
    # "unavailable" means the flight could not be read: storage failed, or the publication was unreadable.
    outcome: FlightOutcome
    # last_refresh of the entry the leader wrote, present only when the outcome is "done".
    last_refresh: Optional[datetime] = None
    # The leader's failure, present when the outcome is "failed" and the failure could be shared.
    failure: Optional[SharedFailure] = None


class QuerySingleFlight:
    """Collapses concurrent blocking executions of one cache key onto one leader.

    Followers wait while the leader holds the lock, then serve the entry it published or fail the
    way it published. A follower runs the query only when the flight itself is unavailable: storage
    errors and unreadable publications fail open to independent execution, never to a query failure.
    """

    def __init__(self, cache_key: str, budget: Budget, variant: str = "") -> None:
        # The hash tag keeps both keys in one Redis Cluster slot so one script can touch both. Runs
        # pair only within one budget and variant, which carry what changes a run's limits or
        # results without reaching the cache key.
        partition = f"{budget}:{variant}" if variant else budget
        self.lock_key = f"query_flight:{{{cache_key}}}:{partition}"
        self.result_key = f"query_flight_result:{{{cache_key}}}:{partition}"
        self._budget = budget
        self._token = uuid.uuid4().hex
        self._held = False
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
        self._held = True
        self._heartbeat = _Heartbeat(self, max_seconds=FLIGHT_MAX_LEADER_SECONDS[self._budget])
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

    def succeed(self, last_refresh: datetime) -> None:
        """Release the lock, telling followers which entry to serve."""
        self._release({"last_refresh": last_refresh.isoformat()})

    def fail(self, failure: Optional[SharedFailure]) -> None:
        """Release the lock, telling followers the leader failed, with the failure when it can be shared."""
        self._release({"failure": None if failure is None else asdict(failure)})

    def release(self) -> None:
        """Release the lock without a publication. Does nothing once the lock is released."""
        self._release(None)

    def _release(self, published: Optional[dict]) -> None:
        if not self._held:
            return
        self._held = False
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

    def wait(self, timeout_seconds: Optional[float] = None) -> FlightWait:
        """Poll until the leader releases the lock, the lock expires, or the timeout elapses. The
        default timeout outlasts the longest a leader can hold the lock."""
        if timeout_seconds is None:
            timeout_seconds = FLIGHT_MAX_LEADER_SECONDS[self._budget] + FLIGHT_LOCK_TTL
        start = time.monotonic()
        deadline = start + timeout_seconds
        interval = FLIGHT_POLL_INTERVAL
        while True:
            result = self._poll()
            if result is not None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result = FlightWait(outcome="timeout")
                break
            time.sleep(min(interval, remaining))
            interval = min(interval * 2, FLIGHT_MAX_POLL_INTERVAL)
        QUERY_SINGLE_FLIGHT_WAIT_SECONDS.observe(time.monotonic() - start)
        return result

    def _poll(self) -> Optional[FlightWait]:
        """None while the leader holds the lock, otherwise what it published."""
        try:
            client = storage.query_cache_raw_client()
            reply = client.register_script(_POLL_SCRIPT)(keys=[self.lock_key, self.result_key])  # type: ignore[union-attr]
        except Exception:
            self._storage_failed("poll")
            return FlightWait(outcome="unavailable")
        if reply[0]:
            return None
        return self._read_publication(reply[1])

    def _read_publication(self, value: Any) -> FlightWait:
        if not value:
            return FlightWait(outcome="released")
        try:
            published = json.loads(value)
            if "failure" in published:
                return FlightWait(outcome="failed", failure=_shared_failure_from(published["failure"]))
            return FlightWait(outcome="done", last_refresh=datetime.fromisoformat(published["last_refresh"]))
        except Exception:
            # A publication this version cannot read, such as one a newer deploy wrote.
            logger.warning("query_single_flight_unreadable_publication", key=self.result_key)
            QUERY_SINGLE_FLIGHT_COUNTER.labels(action="unreadable_publication").inc()
            return FlightWait(outcome="unavailable")

    def _storage_failed(self, operation: str) -> None:
        # A warning without a traceback: a Redis outage would otherwise log one per blocking query.
        logger.warning("query_single_flight_storage_error", operation=operation, key=self.lock_key)
        QUERY_SINGLE_FLIGHT_COUNTER.labels(action="storage_error").inc()


def _shared_failure_from(published: Optional[dict[str, Any]]) -> Optional[SharedFailure]:
    if published is None:
        return None
    # Fields a newer deploy added are dropped, so the failure still rebuilds on this version.
    known = {field.name for field in fields(SharedFailure)}
    return SharedFailure(**{name: value for name, value in published.items() if name in known})


class _Heartbeat:
    """Extends the leader's lock every FLIGHT_HEARTBEAT_INTERVAL until stopped, until the lock is no
    longer the leader's, or until max_seconds have passed. A daemon thread, so a dying process takes
    it down and the lock expires on its own."""

    def __init__(self, flight: QuerySingleFlight, *, max_seconds: float) -> None:
        self._flight = flight
        self._deadline = time.monotonic() + max_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="query-single-flight-heartbeat", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(FLIGHT_HEARTBEAT_INTERVAL):
            if time.monotonic() >= self._deadline:
                break
            # Keep beating through a storage error: the lock is still ours until it expires, and
            # stopping here would hand the flight to a follower while this leader still runs.
            if self._flight.extend() is False:
                break

    def stop(self) -> None:
        # No join: an extend still in flight checks ownership, so it cannot outlive the release.
        self._stop.set()


def _millis(seconds: float) -> int:
    return int(seconds * 1000)
