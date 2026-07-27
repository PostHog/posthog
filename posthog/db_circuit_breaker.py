from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings

import redis
from statshog.defaults.django import statsd

from posthog.redis import get_client

logger = logging.getLogger(__name__)


def _now() -> float:
    return time.time()


# Bumping the version invalidates breaker state from any prior version with
# different key semantics, so a rolling deploy can't mix incompatible writes.
_KEY_PREFIX = "posthog:dbcb:v1"

# Hard cap on how long a single breaker Redis call may block. Redis sits in the
# hot path of every product-DB connection, so it must never be the thing that
# stalls the request it is supposed to be protecting.
_REDIS_OP_TIMEOUT_SECONDS = 0.1

# Floor for how long the open marker is remembered in Redis (decoupled from the
# cooldown) so low-traffic products stay protected across idle gaps while down.
_OPEN_MARKER_MIN_TTL_SECONDS = 300

# Decide whether the breaker should let a connection attempt through. Returns
# {allowed, is_probe, open_until}. While open and within cooldown the request is
# denied without touching the database, and the real Redis deadline is returned
# so each worker can cache it accurately. Once cooldown expires the breaker is
# half-open: a single worker wins the probe lease and is allowed through to test
# recovery; everyone else keeps failing fast (open_until=0, so they don't cache
# and keep re-checking Redis to pick up recovery promptly).
_ALLOW_SCRIPT = """
local open_until = redis.call('GET', KEYS[1])
if not open_until then
    return {1, 0, 0}
end
if tonumber(ARGV[1]) < tonumber(open_until) then
    return {0, 0, tonumber(open_until)}
end
local got = redis.call('SET', KEYS[2], '1', 'NX', 'EX', ARGV[2])
if got then
    return {1, 1, 0}
end
return {0, 0, 0}
"""

# Record a failed connection. A failing probe re-opens the breaker immediately
# and releases the lease. Otherwise the failure counter is incremented within a
# fixed window (TTL set only when the counter is created); crossing the threshold
# opens the breaker. The open marker (KEYS[2]) holds the cooldown deadline as its
# value but is kept for ARGV[6] seconds — far longer than the cooldown — so a
# low-traffic product whose DB stays down through an idle gap still has the open
# marker present when traffic resumes, forcing a single half-open probe instead
# of letting every worker burn the connect timeout. Returns 1 when the breaker is
# open after this failure, else 0.
_FAILURE_SCRIPT = """
local now = tonumber(ARGV[1])
local threshold = tonumber(ARGV[2])
local cooldown = tonumber(ARGV[3])
local window = tonumber(ARGV[4])
local is_probe = ARGV[5]
local open_for = tonumber(ARGV[6])

if is_probe == '1' then
    redis.call('SET', KEYS[2], tostring(now + cooldown), 'EX', open_for)
    redis.call('DEL', KEYS[3])
    redis.call('DEL', KEYS[1])
    return 1
end

local n = redis.call('INCR', KEYS[1])
if n == 1 then
    redis.call('EXPIRE', KEYS[1], window)
end
if n >= threshold then
    redis.call('SET', KEYS[2], tostring(now + cooldown), 'EX', open_for)
    return 1
end
return 0
"""


@dataclass(frozen=True)
class BreakerDecision:
    allowed: bool
    is_probe: bool


_CLOSED = BreakerDecision(allowed=True, is_probe=False)
_DENIED = BreakerDecision(allowed=False, is_probe=False)


@dataclass(frozen=True)
class _BreakerConfig:
    enabled: bool
    failure_threshold: int
    cooldown_seconds: int
    probe_timeout_seconds: int
    window_seconds: int


def _load_config() -> _BreakerConfig:
    return _BreakerConfig(
        enabled=bool(getattr(settings, "PRODUCT_DB_CIRCUIT_BREAKER_ENABLED", False)),
        failure_threshold=int(getattr(settings, "PRODUCT_DB_CIRCUIT_BREAKER_FAILURE_THRESHOLD", 3)),
        cooldown_seconds=int(getattr(settings, "PRODUCT_DB_CIRCUIT_BREAKER_COOLDOWN_SECONDS", 30)),
        probe_timeout_seconds=int(getattr(settings, "PRODUCT_DB_CIRCUIT_BREAKER_PROBE_TIMEOUT_SECONDS", 5)),
        window_seconds=int(getattr(settings, "PRODUCT_DB_CIRCUIT_BREAKER_WINDOW_SECONDS", 30)),
    )


@lru_cache(maxsize=1)
def _get_redis() -> redis.Redis | None:
    """Dedicated, tightly-timed Redis client for the breaker.

    Uses fakeredis in tests. In prod, builds a client with short socket timeouts
    so Redis itself can never block the connection path for more than ~100ms.
    """
    if settings.TEST:
        return get_client()

    redis_url = settings.REDIS_URL
    if not redis_url:
        return None

    return redis.from_url(
        redis_url,
        db=0,
        socket_timeout=_REDIS_OP_TIMEOUT_SECONDS,
        socket_connect_timeout=_REDIS_OP_TIMEOUT_SECONDS,
    )


class ProductDBCircuitBreaker:
    """Per-alias fail-fast circuit breaker for product databases.

    State lives in Redis so one worker tripping the breaker is seen by all 50-200
    pods immediately, rather than each independently burning the connect timeout
    discovering the database is down. Every Redis call is wrapped to fail safe:
    if Redis is slow or unavailable the breaker stays closed and the normal
    connection attempt (with its own ``connect_timeout``) proceeds — the breaker
    must never be what takes a healthy database offline.

    A small in-process cache of the open deadline lets workers skip Redis
    entirely while the breaker is open, so an outage doesn't generate one Redis
    round-trip per request per worker.
    """

    def __init__(self) -> None:
        # Registered lazily off the first client; redis-py's Script handles the
        # EVALSHA-then-load-on-NOSCRIPT dance for us.
        self._allow_script: redis.commands.core.Script | None = None
        self._failure_script: redis.commands.core.Script | None = None
        # alias -> local monotonic-ish deadline (time.time) we believe it's open until
        self._local_open_until: dict[str, float] = {}

    def _keys(self, alias: str) -> tuple[str, str, str]:
        base = f"{_KEY_PREFIX}:{alias}"
        return f"{base}:fails", f"{base}:open_until", f"{base}:probe"

    def before_connect(self, alias: str) -> BreakerDecision:
        config = _load_config()
        if not config.enabled:
            return _CLOSED

        # Local fast-path: if we recently learned the breaker is open, don't even
        # talk to Redis until the cooldown we cached has elapsed.
        cached_until = self._local_open_until.get(alias)
        now = _now()
        if cached_until is not None and now < cached_until:
            return _DENIED

        client = _get_redis()
        if client is None:
            return _CLOSED

        _, open_until_key, probe_key = self._keys(alias)
        if self._allow_script is None:
            self._allow_script = client.register_script(_ALLOW_SCRIPT)
        try:
            result = self._allow_script(
                keys=[open_until_key, probe_key], args=[now, config.probe_timeout_seconds], client=client
            )
        except Exception:
            logger.exception("product_db_circuit_breaker_allow_failed", extra={"alias": alias})
            return _CLOSED

        allowed = bool(result[0])
        is_probe = bool(result[1])
        if allowed:
            self._local_open_until.pop(alias, None)
            return BreakerDecision(allowed=True, is_probe=is_probe)

        # Denied: cache the real Redis deadline so we skip Redis while genuinely
        # open. open_until=0 means the cooldown has elapsed and another worker
        # holds the probe lease — don't cache that, so we keep re-checking Redis
        # and pick up recovery as soon as the probe resolves.
        open_until = float(result[2])
        if open_until > now:
            self._local_open_until[alias] = open_until
        else:
            self._local_open_until.pop(alias, None)
        return _DENIED

    def record_failure(self, alias: str, *, was_probe: bool) -> None:
        config = _load_config()
        if not config.enabled:
            return
        client = _get_redis()
        if client is None:
            return

        fails_key, open_until_key, probe_key = self._keys(alias)
        if self._failure_script is None:
            self._failure_script = client.register_script(_FAILURE_SCRIPT)
        # Capture once so the local deadline matches the open_until Redis computes.
        now = _now()
        # Keep the open marker well past the cooldown so an idle, still-down product
        # forces a single probe (not a connect-timeout stampede) when traffic resumes.
        open_marker_ttl = max(config.cooldown_seconds * 10, _OPEN_MARKER_MIN_TTL_SECONDS)
        try:
            opened = self._failure_script(
                keys=[fails_key, open_until_key, probe_key],
                args=[
                    now,
                    config.failure_threshold,
                    config.cooldown_seconds,
                    config.window_seconds,
                    int(was_probe),
                    open_marker_ttl,
                ],
                client=client,
            )
        except Exception:
            logger.exception("product_db_circuit_breaker_record_failure_failed", extra={"alias": alias})
            return

        if opened:
            self._local_open_until[alias] = now + config.cooldown_seconds
            statsd.incr("product_db_circuit_breaker_opened", tags={"alias": alias})
            logger.warning(
                "product_db_circuit_breaker_opened",
                extra={"alias": alias, "was_probe": was_probe, "cooldown_seconds": config.cooldown_seconds},
            )

    def record_success(self, alias: str, *, was_probe: bool) -> None:
        # Only a successful probe needs to mutate state — it closes the breaker.
        # Successes in the normal closed state are the common case and stay
        # work-free so the healthy hot path costs a single Redis call (the allow).
        if not was_probe:
            return
        if not _load_config().enabled:
            return
        client = _get_redis()
        if client is None:
            return

        fails_key, open_until_key, probe_key = self._keys(alias)
        try:
            client.delete(fails_key, open_until_key, probe_key)
        except Exception:
            logger.exception("product_db_circuit_breaker_record_success_failed", extra={"alias": alias})
            return

        self._local_open_until.pop(alias, None)
        statsd.incr("product_db_circuit_breaker_closed", tags={"alias": alias})
        logger.warning("product_db_circuit_breaker_closed", extra={"alias": alias})


@lru_cache(maxsize=1)
def get_circuit_breaker() -> ProductDBCircuitBreaker:
    return ProductDBCircuitBreaker()
