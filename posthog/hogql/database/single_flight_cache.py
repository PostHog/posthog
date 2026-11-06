import threading
from collections.abc import Callable, Hashable

from cachetools import TTLCache
from prometheus_client import Counter


class _InflightCompute[V]:
    """One in-progress compute for a key. Waiters block on `done` and consume `result` directly,
    so a result that is never admitted to the cache (oversized) still reaches every waiter."""

    __slots__ = ("done", "result")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: V | None = None


class SingleFlightTTLCache[K: Hashable, V]:
    """An in-process TTL cache bounded by total entry weight, where concurrent misses for one key
    wait for a single compute instead of each running it.

    `events` counts hit/miss/oversized lookups; oversized counts computes whose result was too
    heavy to store, so they run again on the next lookup.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float,
        weight_budget: int,
        max_entry_weight: int,
        weigh: Callable[[V], int],
        timer: Callable[[], float],
        events: Counter,
    ) -> None:
        self._max_entry_weight = max_entry_weight
        self._weigh = weigh
        self._events = events
        self._cache: TTLCache[K, V] = TTLCache(maxsize=weight_budget, ttl=ttl_seconds, timer=timer, getsizeof=weigh)
        # cachetools caches are not thread-safe; the lock guards threaded WSGI/Celery workers.
        self._lock = threading.Lock()
        # An entry is retired atomically with the cache store, so a caller always observes either a
        # cached value or an in-flight compute, never neither.
        self._inflight: dict[K, _InflightCompute[V]] = {}

    def get_or_compute(self, key: K, compute: Callable[[], V]) -> V:
        while True:
            with self._lock:
                cached = self._cache.get(key)
                if cached is not None:
                    self._events.labels(result="hit").inc()
                    return cached
                flight = self._inflight.get(key)
                is_owner = flight is None
                if is_owner:
                    flight = _InflightCompute()
                    self._inflight[key] = flight
            assert flight is not None

            if not is_owner:
                flight.done.wait()
                if flight.result is not None:
                    self._events.labels(result="hit").inc()
                    return flight.result
                # The owner's compute raised; loop so one waiter becomes the new owner and retries.
                continue

            self._events.labels(result="miss").inc()
            oversized = False
            try:
                # The compute runs outside the cache lock so one slow key cannot stall every other
                # key's lookups. Cache admission happens before the flight is retired in the finally
                # block, so a new caller always observes either a cached value or an in-flight compute.
                value = compute()
                oversized = self._weigh(value) > self._max_entry_weight
                flight.result = value
                if not oversized:
                    with self._lock:
                        self._cache[key] = value
            finally:
                # Waiters must always wake and the flight must always leave the registry, whatever
                # raised above. A flight that stays registered would hang this key's callers forever.
                with self._lock:
                    self._inflight.pop(key, None)
                flight.done.set()
            if oversized:
                self._events.labels(result="oversized").inc()
            return value

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._inflight.clear()
