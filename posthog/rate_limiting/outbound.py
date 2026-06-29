"""The outbound egress rate limiter facade.

This is the only surface consumers should touch. Call ``acquire`` (async) or ``consume_sync``
with a limiter key whose domain has a registered ``RatePolicy``; it returns True if the call fits
the shared budget, False if it would exceed it. Both are non-blocking — the caller decides what to
do on False (back off and retry, defer, or drop). Consumers depend on this facade, never on the
backing library, so the algorithm/backend stays swappable.
"""

import threading

from posthog.rate_limiting.backends import LimitsBackend
from posthog.rate_limiting.policies import RatePolicy, resolve_policy


def _validate(n: int, policy: RatePolicy) -> None:
    if n < 1:
        raise ValueError(f"rate limiter weight must be >= 1, got {n}")
    smallest = min(count for count, _ in policy.limits)
    if n > smallest:
        # limits treats a weight larger than the limit as permanently unsatisfiable, so the caller
        # would back off forever rather than ever be granted. Fail loudly instead of silently.
        raise ValueError(f"weight {n} exceeds the tightest configured limit ({smallest}); it can never be granted")


class OutboundRateLimiter:
    def __init__(self, backend: LimitsBackend | None = None) -> None:
        self._backend = backend or LimitsBackend()

    async def acquire(self, key: str, n: int = 1) -> bool:
        """Reserve ``n`` units against ``key``'s budget. Returns False if it would exceed it."""
        policy = resolve_policy(key)
        _validate(n, policy)
        return await self._backend.acquire(key, policy, n)

    def consume_sync(self, key: str, n: int = 1) -> bool:
        """Non-blocking sync variant for callers outside an event loop."""
        policy = resolve_policy(key)
        _validate(n, policy)
        return self._backend.consume_sync(key, policy, n)


_limiter: OutboundRateLimiter | None = None
_limiter_lock = threading.Lock()


def get_outbound_rate_limiter() -> OutboundRateLimiter:
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                _limiter = OutboundRateLimiter()
    return _limiter
