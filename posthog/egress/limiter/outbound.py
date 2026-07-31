"""The outbound egress rate limiter facade.

This is the only surface consumers should touch. Call ``acquire`` (async) or ``consume_sync``
with a limiter key whose domain has a registered ``RatePolicy``; it returns True if the call fits
the shared budget, False if it would exceed it. Both are non-blocking — the caller decides what to
do on False (back off and retry, defer, or drop). Consumers depend on this facade, never on the
backing library, so the algorithm/backend stays swappable.
"""

import threading

from posthog.egress.limiter.backends import LimitsBackend
from posthog.egress.limiter.policies import Priority, RatePolicy, resolve_policy
from posthog.egress.observability.observability import record_outbound_decision


def _domain_of(key: str) -> str:
    # resolve_policy already validated the key shape, so the first segment is the domain.
    return key.partition(":")[0]


def _validate(n: int, policy: RatePolicy, priority: Priority) -> None:
    if n < 1:
        raise ValueError(f"rate limiter weight must be >= 1, got {n}")
    for count, _ in policy.limits:
        reserve = policy.reserve_amount(priority, count)
        if n + reserve > count:
            # limits treats a weight larger than the limit as permanently unsatisfiable, so the
            # caller would back off forever rather than ever be granted. The priority's reserved floor
            # eats into that headroom, so check the inflated weight, not just n. Fail loudly.
            raise ValueError(
                f"weight {n} plus reserved floor {reserve} for priority {priority.name} exceeds the "
                f"limit {count}; it can never be granted"
            )


class OutboundRateLimiter:
    def __init__(self, backend: LimitsBackend | None = None) -> None:
        self._backend = backend or LimitsBackend()

    async def acquire(
        self, key: str, n: int = 1, *, priority: Priority = Priority.NORMAL, source: str = "unknown"
    ) -> bool:
        """Reserve ``n`` units against ``key``'s budget. Returns False if it would exceed it (or, for a
        lower ``priority``, would dip into the reserve owed to higher-priority traffic)."""
        policy = resolve_policy(key)
        _validate(n, policy, priority)
        granted = await self._backend.acquire(key, policy, n, priority)
        record_outbound_decision(domain=_domain_of(key), source=source, priority=priority.value, granted=granted)
        return granted

    def consume_sync(
        self, key: str, n: int = 1, *, priority: Priority = Priority.NORMAL, source: str = "unknown"
    ) -> bool:
        """Non-blocking sync variant for callers outside an event loop."""
        policy = resolve_policy(key)
        _validate(n, policy, priority)
        granted = self._backend.consume_sync(key, policy, n, priority)
        record_outbound_decision(domain=_domain_of(key), source=source, priority=priority.value, granted=granted)
        return granted


_limiter: OutboundRateLimiter | None = None
_limiter_lock = threading.Lock()


def get_outbound_rate_limiter() -> OutboundRateLimiter:
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                _limiter = OutboundRateLimiter()
    return _limiter
