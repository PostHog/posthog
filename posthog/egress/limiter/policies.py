"""Outbound egress rate policies and their registry.

A *policy* is a budget for calls leaving PostHog to a third-party API. Consumers identify a
budget with a limiter key shaped ``"{domain}:{scope}:{id}"`` (e.g. ``"github:installation:123"``);
the facade resolves the key to a policy by its ``domain`` (the first segment).

Policies are registered as *providers* — a callable receiving the full limiter key and returning a
``RatePolicy`` — so a budget can be read from Django settings at resolve time (not frozen at import)
and can vary per scope (e.g. per GitHub installation tier). Pass a plain ``RatePolicy`` for a static
budget. This module is backend-agnostic (no Redis, no limiter library), which keeps the limiter
backend swappable.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from math import floor
from types import MappingProxyType

from django.conf import settings

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


# BATCH calls are denied once 70% of a window is consumed, NORMAL at 90%, and CRITICAL may use the
# full budget. Every policy gets this ladder unless it passes its own, because a policy without a
# reserve admits every lane to the full budget and makes the caller's priority meaningless.
DEFAULT_RESERVE: Mapping[Priority, float] = MappingProxyType({Priority.BATCH: 0.30, Priority.NORMAL: 0.10})


@dataclass(frozen=True)
class RatePolicy:
    """A budget: one or more ``(count, period_seconds)`` limits enforced together.

    ``in_memory_divider`` shrinks the per-process fallback budget used when Redis is unavailable:
    each process would otherwise get the full budget, so N processes together would allow N× the
    shared limit. The fallback is best-effort only — the consumer's reactive backoff (e.g. honoring
    a 429) is the real backstop.

    ``reserve`` maps a :class:`Priority` to the fraction of each window's budget that must remain
    free for a call of that priority to be admitted. It defaults to :data:`DEFAULT_RESERVE`. A
    priority absent from the map reserves nothing (0.0), so ``reserve={}`` admits every lane to the
    full budget. Pass it only for a domain with no higher-priority traffic to protect. Fractions are
    validated to ``[0, 1)`` (1.0 would reserve the whole window and deny the priority forever).
    """

    limits: tuple[RateLimit, ...]
    in_memory_divider: int = 1
    reserve: Mapping[Priority, float] = DEFAULT_RESERVE

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
        floor (not round/ceil) so a 0 fraction reserves exactly 0 and a flat policy admits every lane
        to the full window. Single source for both admission (backend) and validation (facade), so
        the two can't drift."""
        return floor(self.reserve_fraction(priority) * count)


PolicyProvider = Callable[[str], RatePolicy]


def per_minute_and_hourly_policy(
    *,
    per_minute_setting: str,
    per_minute_default: int,
    hourly_setting: str,
    hourly_default: int,
    reserve: Mapping[Priority, float] = DEFAULT_RESERVE,
) -> PolicyProvider:
    """A provider for the common budget: a per-minute rate that smooths bursts and an hourly rate
    that caps total spend, both read from settings on each acquire so an override applies without a
    process restart. ``in_memory_divider`` is 4 because a Redis outage leaves each worker process
    with its own counter."""

    def provider(_key: str) -> RatePolicy:
        return RatePolicy(
            limits=(
                (int(getattr(settings, per_minute_setting, per_minute_default)), 60.0),
                (int(getattr(settings, hourly_setting, hourly_default)), 3600.0),
            ),
            in_memory_divider=4,
            reserve=reserve,
        )

    return provider


_REGISTRY: dict[str, PolicyProvider] = {}


def register_policy(domain: str, policy: RatePolicy | PolicyProvider) -> None:
    """Register the budget for a key domain. Pass a ``RatePolicy`` for a static budget, or a
    callable taking the full limiter key to resolve it lazily (e.g. from settings, or per scope)
    on each acquire."""
    if isinstance(policy, RatePolicy):
        _REGISTRY[domain] = lambda _key: policy
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
    return provider(key)
