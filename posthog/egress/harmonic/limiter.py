"""Harmonic egress budget.

Harmonic bills one account-wide rate limit — there is one ``HARMONIC_API_KEY`` per PostHog
instance, not one per installation or team — so every call anywhere in the codebase draws from a
single shared budget under the constant key ``harmonic:account:default``.

Harmonic's API reference documents a limit of 10 requests per second for most endpoints and answers
429 above it. The default budget of 15 per second sits above
that on purpose: the BATCH reserve floors to 4 of 15 units, so the bulk lane is admitted up to 11 calls a
second, next to the documented rate.

Two very different consumers share this budget, so the priority lanes matter:
- CRITICAL (interactive): signup enrichment and the ICP re-enrichment sweep run inside a
  90-second Temporal activity budget and must never be starved by bulk traffic.
- BATCH: the Salesforce enrichment sweep works through a large account backlog and can back off
  when the budget is tight.

Importing this module registers the policy as a side effect — import it (directly or via
``consume_harmonic``/``acquire_harmonic``) before using the ``harmonic:account:default`` key.
"""

from django.conf import settings

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy

HARMONIC_DOMAIN = "harmonic"

# One account per instance — Harmonic meters usage account-wide, not per installation.
ACCOUNT_SCOPE_ID = "default"
HARMONIC_ACCOUNT_KEY = f"{HARMONIC_DOMAIN}:account:{ACCOUNT_SCOPE_ID}"

_DEFAULT_PER_SECOND_BUDGET = 15

HARMONIC_WINDOW_SECONDS = 1.0


# Registered as a provider so the budget is read at acquire time — a settings override applies
# without a process restart, matching the other egress domains. The default reserve ladder keeps the
# interactive lane (CRITICAL) from being starved by the bulk enrichment job saturating the counter.
def _harmonic_policy(_key: str) -> RatePolicy:
    per_second = int(getattr(settings, "HARMONIC_EGRESS_PER_SECOND_BUDGET", _DEFAULT_PER_SECOND_BUDGET))
    return RatePolicy(limits=((per_second, HARMONIC_WINDOW_SECONDS),), in_memory_divider=4)


register_policy(HARMONIC_DOMAIN, _harmonic_policy)


def consume_harmonic(priority: Priority = Priority.NORMAL, source: str = "unknown") -> bool:
    """Sync gate, for callers outside an event loop. Returns False when the budget (or this
    priority's reserved floor) is exhausted — degrade gracefully rather than calling out."""
    return get_outbound_rate_limiter().consume_sync(HARMONIC_ACCOUNT_KEY, priority=priority, source=source)


async def acquire_harmonic(priority: Priority = Priority.NORMAL, source: str = "unknown") -> bool:
    """Async gate — the primary path, since the Harmonic client is aiohttp-based."""
    return await get_outbound_rate_limiter().acquire(HARMONIC_ACCOUNT_KEY, priority=priority, source=source)


def pace_seconds_harmonic(priority: Priority = Priority.NORMAL) -> float:
    """Seconds to wait before the next call, for a caller that can wait (the bulk enrichment job
    walking pages) so it spreads its share of the budget instead of bursting into it and being
    shed. Advisory only — acquire/consume remain the sole admission authority."""
    return get_outbound_rate_limiter().pace_seconds(HARMONIC_ACCOUNT_KEY, priority=priority)


def admission_interval_harmonic(priority: Priority = Priority.NORMAL) -> float:
    """Seconds between admissions that keep a steady caller inside this priority's share of the
    budget, from the policy alone. See OutboundRateLimiter.admission_interval_seconds."""
    return get_outbound_rate_limiter().admission_interval_seconds(HARMONIC_ACCOUNT_KEY, priority=priority)
