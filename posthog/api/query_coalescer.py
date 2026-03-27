import re
import time
import uuid
import hashlib
import threading
from enum import StrEnum
from typing import TYPE_CHECKING, Optional
from urllib.parse import parse_qs, urlencode

from django.http import HttpRequest, HttpResponse

import orjson
import structlog
import posthoganalytics
from prometheus_client import Counter, Histogram
from redis.exceptions import RedisError

from posthog import (
    redis as posthog_redis,
    settings,
)

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
            return orjson.loads(value)
        except (RedisError, orjson.JSONDecodeError):
            return None

    def store_success_response(self, status_code: int, content: bytes, content_type: str) -> None:
        """Store full HTTP success response for followers to replay."""
        try:
            payload = orjson.dumps(
                {
                    "status": status_code,
                    "body": content.decode("utf-8") if isinstance(content, bytes) else content,
                    "content_type": content_type,
                }
            )
            self._redis.set(self._done_key, payload, ex=LOCK_TTL_SECONDS)
            self._redis.publish(self._channel_key, CoalesceSignal.DONE)
        except RedisError:
            pass

    def get_success_response(self) -> Optional[dict]:
        """Read stored HTTP success response. Returns {"status": int, "body": str, "content_type": str} or None."""
        try:
            value = self._redis.get(self._done_key)
            if value is None:
                return None
            parsed = orjson.loads(value)
            if isinstance(parsed, dict) and "status" in parsed:
                return parsed
            return None
        except (RedisError, orjson.JSONDecodeError):
            return None

    def store_error_response(self, status_code: int, content: bytes) -> None:
        """Store HTTP error response for followers to replay."""
        try:
            payload = orjson.dumps(
                {
                    "status": status_code,
                    "body": content.decode("utf-8") if isinstance(content, bytes) else content,
                }
            )
            self._redis.set(self._error_key, payload, ex=ERROR_TTL_SECONDS)
            self._redis.publish(self._channel_key, CoalesceSignal.ERROR)
        except RedisError:
            pass

    def signal_error(self) -> None:
        """Signal followers that the leader encountered a client error (4xx).

        Publishes ERROR to the channel without storing a response body,
        so followers stop waiting and execute independently.
        """
        try:
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


_TEAM_ID_RE = re.compile(r"^/api/(?:environments|projects)/(\d+)/")

_COALESCE_PATH_PATTERNS = [
    re.compile(r"^/api/(?:environments|projects)/\d+/query/$"),
    re.compile(r"^/api/(?:environments|projects)/\d+/insights/trend/$"),  # legacy endpoint
    re.compile(r"^/api/(?:environments|projects)/\d+/insights/funnel/$"),  # legacy endpoint
    re.compile(r"^/api/(?:environments|projects)/\d+/insights/\d+/$"),
]


class QueryCoalescingMiddleware:
    """Coalesce concurrent identical query requests.

    For matched endpoints, only one request (leader) executes while
    concurrent identical requests (followers) wait and get the same response.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method not in ("GET", "POST"):
            return self.get_response(request)

        if not any(p.match(request.path) for p in _COALESCE_PATH_PATTERNS):
            return self.get_response(request)

        team_id = self._extract_team_id(request.path)
        if not team_id:
            return self.get_response(request)

        enabled = posthoganalytics.feature_enabled("http-query-coalescing", str(team_id))

        key = self._compute_key(team_id, request)
        coalescer = QueryCoalescer(key, dry_run=not enabled)

        try:
            is_leader = coalescer.try_acquire()
        except RedisError:
            logger.warning("query_coalescing_middleware_redis_error", msg="redis unavailable, skipping coalescing")
            return self.get_response(request)

        if is_leader:
            return self._handle_leader(request, coalescer)

        if not enabled:
            return self.get_response(request)

        return self._handle_follower(request, coalescer)

    def _handle_leader(self, request: HttpRequest, coalescer: QueryCoalescer) -> HttpResponse:
        try:
            response = self.get_response(request)
            # Force render DRF responses so we can capture the body
            if hasattr(response, "render") and callable(response.render):
                response.render()
            content_type = response.get("Content-Type", "application/json")
            if response.status_code < 400 or response.status_code >= 500:
                # Coalesce successes (2xx) and server errors (5xx).
                # 4xx are user-specific (permissions, validation) and must not be shared.
                coalescer.store_success_response(response.status_code, response.content, content_type)
            else:
                coalescer.signal_error()
            return response
        except Exception:
            coalescer.signal_error()
            raise
        finally:
            coalescer.cleanup()

    def _handle_follower(self, request: HttpRequest, coalescer: QueryCoalescer) -> HttpResponse:
        log = logger.bind(coalescing_key=coalescer.coalescing_key)
        log.info("query_coalescing_middleware_follower_waiting")

        signal = coalescer.wait_for_signal(max_wait=settings.QUERY_COALESCING_MAX_WAIT_SECONDS)

        if signal == CoalesceSignal.DONE:
            data = coalescer.get_success_response()
            if data:
                log.info("query_coalescing_middleware_follower_done")
                # Attach cached response for the view mixin to gate behind permissions
                request.META["_coalesced_response"] = data
                return self.get_response(request)
            log.warning("query_coalescing_middleware_follower_done_read_failed")

        if signal == CoalesceSignal.ERROR:
            log.info("query_coalescing_middleware_follower_error")
        elif signal == CoalesceSignal.TIMEOUT:
            log.warning("query_coalescing_middleware_follower_timeout")
        elif signal == CoalesceSignal.CRASHED:
            log.warning("query_coalescing_middleware_follower_crashed")

        # Fall through: execute the request normally
        log.info("query_coalescing_middleware_follower_fallthrough", signal=signal)
        return self.get_response(request)

    @staticmethod
    def _extract_team_id(path: str) -> int | None:
        match = _TEAM_ID_RE.match(path)
        if not match:
            return None
        return int(match.group(1))

    # Fields that are unique per request and should not affect coalescing
    _IGNORED_KEY_FIELDS = {"client_query_id", "session_id"}

    @staticmethod
    def _compute_key(team_id: int, request: HttpRequest) -> str:
        if request.method == "GET":
            params = parse_qs(request.META.get("QUERY_STRING", ""))
            for field in QueryCoalescingMiddleware._IGNORED_KEY_FIELDS:
                params.pop(field, None)
            normalized = urlencode(sorted(params.items()), doseq=True).encode()
        else:
            try:
                data = orjson.loads(request.body)
                if isinstance(data, dict):
                    for field in QueryCoalescingMiddleware._IGNORED_KEY_FIELDS:
                        data.pop(field, None)
                normalized = orjson.dumps(data, option=orjson.OPT_SORT_KEYS)
            except ValueError:
                normalized = request.body

        raw = f"{team_id}:{request.method}:{request.path}:{normalized.decode()}"
        return hashlib.sha256(raw.encode()).hexdigest()


if TYPE_CHECKING:
    from rest_framework.views import APIView

    _MixinBase = APIView
else:
    _MixinBase = object


class QueryCoalescingMixin(_MixinBase):
    """DRF ViewSet mixin that gates coalesced responses behind permission checks.

    The QueryCoalescingMiddleware attaches cached response data to
    request.META["_coalesced_response"] for followers. This mixin runs DRF's
    initial() (auth + permissions + throttling) before returning the
    cached response, ensuring the request is authorized.
    """

    def dispatch(self, request, *args, **kwargs):
        coalesced = request.META.get("_coalesced_response")
        if coalesced is None:
            return super().dispatch(request, *args, **kwargs)

        request = self.initialize_request(request, *args, **kwargs)
        self.request = request
        try:
            self.initial(request, *args, **kwargs)
        except Exception as exc:
            return self.handle_exception(exc)

        return HttpResponse(
            coalesced["body"],
            status=coalesced["status"],
            content_type=coalesced.get("content_type", "application/json"),
        )
