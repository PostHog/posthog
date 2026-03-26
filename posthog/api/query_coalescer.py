import json
import time
import uuid
import hashlib
import threading
from enum import StrEnum
from typing import Optional

import structlog
from prometheus_client import Counter, Histogram
from redis.exceptions import RedisError

from posthog import redis as posthog_redis

logger = structlog.get_logger(__name__)

LOCK_KEY_PREFIX = "http_qc"
DONE_KEY_PREFIX = "http_qc_done"
ERROR_KEY_PREFIX = "http_qc_err"
CHANNEL_PREFIX = "http_qc_ch"
LOCK_TTL_SECONDS = 60
ERROR_TTL_SECONDS = 60
POLL_INTERVAL_SECONDS = 0.2
HEARTBEAT_INTERVAL_SECONDS = 5

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


class CoalesceSignal(StrEnum):
    DONE = "done"
    ERROR = "error"
    TIMEOUT = "timeout"
    CRASHED = "crashed"


def compute_coalescing_key(team_id: int, query_json: str) -> str:
    raw = f"{team_id}:{query_json}"
    return hashlib.sha256(raw.encode()).hexdigest()


class _Heartbeat:
    def __init__(self, redis, lock_key: str, lock_value: str, channel_key: str):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(redis, lock_key, lock_value, channel_key), daemon=True)
        self._thread.start()

    def _run(self, redis, lock_key: str, lock_value: str, channel_key: str) -> None:
        while not self._stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                redis.eval(_EXTEND_LOCK_SCRIPT, 1, lock_key, lock_value, LOCK_TTL_SECONDS)
                redis.publish(channel_key, "heartbeat")
            except RedisError:
                break

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


class QueryCoalescer:
    """Query coalescer.

    One request (leader) acquires a Redis lock and executes the query.
    Concurrent requests (followers) subscribe to a pub/sub channel and wait
    for the leader to signal done/error, or detect a crash via lock disappearing.
    """

    def __init__(self, coalescing_key: str, *, dry_run: bool = False):
        self.coalescing_key = coalescing_key
        self._dry_run = dry_run
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

    @property
    def _channel_key(self) -> str:
        return f"{CHANNEL_PREFIX}:{self.coalescing_key}"

    def try_acquire(self) -> bool:
        """Attempt to become leader. Returns True if acquired, starts heartbeat."""
        acquired = self._redis.set(self._lock_key, self._lock_value, nx=True, ex=LOCK_TTL_SECONDS)
        self._is_leader = bool(acquired)
        if self._is_leader:
            self._redis.delete(self._done_key, self._error_key)
            self._heartbeat = _Heartbeat(self._redis, self._lock_key, self._lock_value, self._channel_key)
            query_coalesce_counter.labels(outcome="leader").inc()
        elif self._dry_run:
            query_coalesce_counter.labels(outcome="follower_dry_run").inc()
        else:
            query_coalesce_counter.labels(outcome="follower").inc()
        return self._is_leader

    def wait_for_signal(self, max_wait: float) -> CoalesceSignal:
        """Block until leader signals completion.

        Subscribes to a Redis pub/sub channel. The leader publishes
        done/error for instant wake-up and heartbeats for liveness.
        If no message arrives within 2 heartbeat intervals the leader
        is assumed crashed.
        """
        start = time.monotonic()
        last_message = start
        crash_timeout = 2 * HEARTBEAT_INTERVAL_SECONDS
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(self._channel_key)

        try:
            while (time.monotonic() - start) < max_wait:
                if self._redis.get(self._done_key):
                    query_coalesce_wait_histogram.observe(time.monotonic() - start)
                    query_coalesce_counter.labels(outcome="follower_done").inc()
                    return CoalesceSignal.DONE

                if self._redis.get(self._error_key):
                    query_coalesce_wait_histogram.observe(time.monotonic() - start)
                    query_coalesce_counter.labels(outcome="follower_error").inc()
                    return CoalesceSignal.ERROR

                # If we haven't received a heartbeat in some time, then the leader crashed.
                if (time.monotonic() - last_message) > crash_timeout:
                    query_coalesce_counter.labels(outcome="follower_crashed").inc()
                    return CoalesceSignal.CRASHED

                if pubsub.get_message(timeout=POLL_INTERVAL_SECONDS) is not None:
                    last_message = time.monotonic()

            query_coalesce_counter.labels(outcome="follower_timeout").inc()
            return CoalesceSignal.TIMEOUT
        finally:
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except Exception:
                pass

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
            self._redis.publish(self._channel_key, CoalesceSignal.DONE)
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
            self._redis.publish(self._channel_key, CoalesceSignal.ERROR)
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
