"""Outbound egress rate policies and their registry.

A *policy* is a budget for calls leaving PostHog to a third-party API. Consumers identify a
budget with a limiter key shaped ``"{domain}:{scope}:{id}"`` (e.g. ``"github:installation:123"``);
the facade resolves the key to a policy by its ``domain`` (the first segment).

Policies are registered as *providers* — a zero-arg callable returning a ``RatePolicy`` — so a
budget sourced from Django settings is read at resolve time, not frozen at import. Pass a plain
``RatePolicy`` for a static budget. This module is backend-agnostic (no Redis, no limiter library),
which keeps the limiter backend swappable.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from math import floor

# (count, period_seconds) — one rate constraint. A policy may carry several; they are all enforced
# together, so you can cap the hour AND smooth per-minute bursts on the same key.
RateLimit = tuple[int, float]


class Priority(Enum):
    """How sheddable a call is when the shared budget gets tight. All priorities draw from the SAME
    per-key counter — the lane only changes how much headroom must stay free for the call to be
    admitted, so deferrable bulk traffic (``BATCH``) is denied before critical traffic as the budget
    fills, without ever splitting the budget into separate buckets."""

    CRITICAL = "critical"  # may use the whole budget — never shed
    NORMAL = "normal"  # default — yields a small reserve to CRITICAL
    BATCH = "batch"  # deferrable bulk — yields the largest reserve, shed first


@dataclass(frozen=True)
class RatePolicy:
    """A budget: one or more ``(count, period_seconds)`` limits enforced together.

    ``in_memory_divider`` shrinks the per-process fallback budget used when Redis is unavailable:
    each process would otherwise get the full budget, so N processes together would allow N× the
    shared limit. The fallback is best-effort only — the consumer's reactive backoff (e.g. honoring
    a 429) is the real backstop.

    ``reserve`` maps a :class:`Priority` to the fraction of each window's budget that must remain
    free for a call of that priority to be admitted. A priority absent from the map reserves nothing
    (0.0), so an empty ``reserve`` keeps every call critical-equivalent — exactly the pre-priority
    behavior. Fractions are validated to ``[0, 1)`` (1.0 would reserve the whole window and deny the
    priority forever).
    """

    limits: tuple[RateLimit, ...]
    in_memory_divider: int = 1
    reserve: Mapping[Priority, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # A policy with no limits would let every call through, defeating the point. Reject it at
        # definition time rather than surfacing an opaque "min() arg is empty" deep in the facade.
        if not self.limits:
            raise ValueError("RatePolicy.limits must declare at least one (count, period_seconds) limit")
        for priority, fraction in self.reserve.items():
            if not (0.0 <= fraction < 1.0):
                raise ValueError(f"RatePolicy.reserve[{priority.name}] must be in [0, 1), got {fraction}")

    def reserve_fraction(self, priority: Priority) -> float:
        """Reserved-headroom fraction for ``priority`` — 0.0 when the priority isn't configured."""
        return self.reserve.get(priority, 0.0)

    def reserve_amount(self, priority: Priority, count: int) -> int:
        """Units of a window of size ``count`` this priority must leave free: ``floor(fraction * count)``.
        floor (not round/ceil) so a 0 fraction reserves exactly 0, keeping the no-reserve path
        bit-identical to pre-priority behavior. Single source for both admission (backend) and
        validation (facade), so the two can't drift."""
        return floor(self.reserve_fraction(priority) * count)


PolicyProvider = Callable[[], RatePolicy]

_REGISTRY: dict[str, PolicyProvider] = {}


def register_policy(domain: str, policy: RatePolicy | PolicyProvider) -> None:
    """Register the budget for a key domain. Pass a ``RatePolicy`` for a static budget, or a
    zero-arg callable to resolve it lazily (e.g. from settings) on each acquire."""
    if isinstance(policy, RatePolicy):
        _REGISTRY[domain] = lambda: policy
    else:
        _REGISTRY[domain] = policy


def resolve_policy(key: str) -> RatePolicy:
    domain, sep, _rest = key.partition(":")
    if not sep or not domain:
        raise ValueError(f"Malformed limiter key '{key}'; expected '{{domain}}:{{scope}}:{{id}}'")
    provider = _REGISTRY.get(domain)
    if provider is None:
        raise ValueError(
            f"No outbound rate policy registered for domain '{domain}' (key '{key}'); "
            "register one with register_policy() before using this key"
        )
    return provider()
