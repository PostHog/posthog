import json
import time
import uuid
import random
import hashlib
import threading
from typing import Optional

import structlog
from prometheus_client import Counter, Histogram
from redis.exceptions import RedisError

from posthog import redis as posthog_redis

logger = structlog.get_logger(__name__)

LOCK_KEY_PREFIX = "http_qc"
DONE_KEY_PREFIX = "http_qc_done"
ERROR_KEY_PREFIX = "http_qc_err"
LOCK_TTL_SECONDS = 60
ERROR_TTL_SECONDS = 60
POLL_INTERVAL_SECONDS = 0.2
HEARTBEAT_INTERVAL_SECONDS = 20

_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""

_EXTEND_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], ARGV[2])
end
return 0
"""

query_coalesce_counter = Counter(
    "posthog_query_coalesce_total",
    "Query coalescing outcomes",
    labelnames=["outcome"],
)

query_coalesce_wait_histogram = Histogram(
    "posthog_query_coalesce_wait_seconds",
    "Time followers spent waiting for leader result",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 60],
)


def compute_coalescing_key(team_id: int, query_json: str) -> str:
    raw = f"{team_id}:{query_json}"
    return hashlib.sha256(raw.encode()).hexdigest()


class _Heartbeat:
    def __init__(self, redis, lock_key: str, lock_value: str):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(redis, lock_key, lock_value), daemon=True)
        self._thread.start()

    def _run(self, redis, lock_key: str, lock_value: str) -> None:
        while not self._stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                redis.eval(_EXTEND_LOCK_SCRIPT, 1, lock_key, lock_value, LOCK_TTL_SECONDS)
            except RedisError:
                break

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


class QueryCoalescer:
    """HTTP-layer query coalescer.

    One request (leader) acquires a Redis lock and executes the query.
    Concurrent requests (followers) poll until the leader signals done,
    then either replay the stored error response or re-execute to hit fresh cache.
    """

    def __init__(self, coalescing_key: str, *, dry_run: bool = False):
        self.coalescing_key = coalescing_key
        self.dry_run = dry_run
        self._lock_value: str = uuid.uuid4().hex
        self._is_leader: bool = False
        self._heartbeat: Optional[_Heartbeat] = None
        self._redis = posthog_redis.get_client()

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    @property
    def _lock_key(self) -> str:
        return f"{LOCK_KEY_PREFIX}:{self.coalescing_key}"

    @property
    def _done_key(self) -> str:
        return f"{DONE_KEY_PREFIX}:{self.coalescing_key}"

    @property
    def _error_key(self) -> str:
        return f"{ERROR_KEY_PREFIX}:{self.coalescing_key}"

    def try_acquire(self) -> bool:
        """Attempt to become leader. Returns True if acquired, starts heartbeat."""
        acquired = self._redis.set(self._lock_key, self._lock_value, nx=True, ex=LOCK_TTL_SECONDS)
        self._is_leader = bool(acquired)
        if self._is_leader:
            self._redis.delete(self._done_key, self._error_key)
            self._heartbeat = _Heartbeat(self._redis, self._lock_key, self._lock_value)
            query_coalesce_counter.labels(outcome="leader").inc()
        elif self.dry_run:
            query_coalesce_counter.labels(outcome="follower_dry_run").inc()
        else:
            query_coalesce_counter.labels(outcome="follower").inc()
        return self._is_leader

    def wait_for_signal(self, max_wait: float) -> str:
        """Block until leader signals completion. Returns outcome string.

        Returns:
            "done" — leader succeeded, follower should re-execute to hit cache
            "error" — leader stored an HTTP error response
            "timeout" — max_wait exceeded
            "crashed" — leader lock disappeared without done/error
        """
        if self.dry_run:
            return "timeout"

        start = time.monotonic()

        while (time.monotonic() - start) < max_wait:
            if self._redis.get(self._done_key):
                query_coalesce_wait_histogram.observe(time.monotonic() - start)
                query_coalesce_counter.labels(outcome="follower_done").inc()
                return "done"

            if self._redis.get(self._error_key):
                query_coalesce_wait_histogram.observe(time.monotonic() - start)
                query_coalesce_counter.labels(outcome="follower_error").inc()
                return "error"

            if self._redis.get(self._lock_key) is None:
                # Leader gone - check one more time for done/error set between checks
                if self._redis.get(self._done_key):
                    query_coalesce_wait_histogram.observe(time.monotonic() - start)
                    query_coalesce_counter.labels(outcome="follower_done").inc()
                    return "done"
                if self._redis.get(self._error_key):
                    query_coalesce_wait_histogram.observe(time.monotonic() - start)
                    query_coalesce_counter.labels(outcome="follower_error").inc()
                    return "error"
                query_coalesce_counter.labels(outcome="follower_crashed").inc()
                return "crashed"

            time.sleep(POLL_INTERVAL_SECONDS * (0.2 + random.random()))

        query_coalesce_counter.labels(outcome="follower_timeout").inc()
        return "timeout"

    def get_error_response(self) -> Optional[dict]:
        """Read stored HTTP error response. Returns {"status": int, "body": str} or None."""
        try:
            value = self._redis.get(self._error_key)
            if value is None:
                return None
            raw = value.decode("utf-8") if isinstance(value, bytes) else value
            return json.loads(raw)
        except (RedisError, json.JSONDecodeError):
            return None

    def mark_done(self) -> None:
        """Signal that leader completed successfully."""
        try:
            self._redis.set(self._done_key, "1", ex=LOCK_TTL_SECONDS)
        except RedisError:
            pass

    def store_error_response(self, status_code: int, content: bytes) -> None:
        """Store HTTP error response for followers to replay."""
        try:
            payload = json.dumps(
                {
                    "status": status_code,
                    "body": content.decode("utf-8") if isinstance(content, bytes) else content,
                }
            )
            self._redis.set(self._error_key, payload, ex=ERROR_TTL_SECONDS)
        except RedisError:
            pass

    def cleanup(self) -> None:
        """Stop heartbeat and release lock. Call in finally block."""
        if self._heartbeat:
            self._heartbeat.stop()
            self._heartbeat = None
        if self._is_leader and self._lock_value:
            try:
                self._redis.eval(_RELEASE_LOCK_SCRIPT, 1, self._lock_key, self._lock_value)
            except RedisError:
                pass
