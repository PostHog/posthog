"""Perplexity egress budget.

Perplexity applies its Agent API request limit to the whole API organization, shared across every
key, and a PostHog instance holds a single ``PERPLEXITY_API_KEY``, so the whole instance draws from
one shared budget under a constant scope. Perplexity's limits depend on the account's usage tier,
which the running process cannot see, so the defaults below are operator ceilings on spend: they
stop a runaway caller from spending money, and they do not mirror Perplexity's own limit. Raise
them in settings when real traffic outgrows them.

Importing this module registers the policy as a side effect, so import it (directly or via
``consume_perplexity_sync``) before using a ``perplexity:...`` limiter key.
"""

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, per_minute_and_hourly_policy, register_policy

PERPLEXITY_DOMAIN = "perplexity"

ACCOUNT_SCOPE_ID = "default"
PERPLEXITY_ACCOUNT_KEY = f"{PERPLEXITY_DOMAIN}:account:{ACCOUNT_SCOPE_ID}"

register_policy(
    PERPLEXITY_DOMAIN,
    per_minute_and_hourly_policy(
        per_minute_setting="PERPLEXITY_EGRESS_PER_MINUTE_BUDGET",
        per_minute_default=60,
        hourly_setting="PERPLEXITY_EGRESS_HOURLY_BUDGET",
        hourly_default=2_000,
    ),
)


def consume_perplexity_sync(n: int = 1, *, priority: Priority = Priority.BATCH, source: str = "unknown") -> bool:
    """Reserve ``n`` requests against the instance's Perplexity budget. Returns False when the budget
    (or this ``priority``'s reserved floor) is exhausted, so degrade rather than calling out."""
    return get_outbound_rate_limiter().consume_sync(PERPLEXITY_ACCOUNT_KEY, n, priority=priority, source=source)


def pace_seconds_perplexity(priority: Priority = Priority.BATCH) -> float:
    """Seconds a caller that can wait should wait before its next call, so a batch run spreads its
    share of the budget instead of being shed. Advisory only: ``consume_perplexity_sync`` stays the
    admission authority."""
    return get_outbound_rate_limiter().pace_seconds(PERPLEXITY_ACCOUNT_KEY, priority=priority)


def admission_interval_perplexity(priority: Priority = Priority.BATCH) -> float:
    """Seconds between admissions that keep a steady caller inside this priority's share of every
    window, from the policy alone. See ``OutboundRateLimiter.admission_interval_seconds``."""
    return get_outbound_rate_limiter().admission_interval_seconds(PERPLEXITY_ACCOUNT_KEY, priority=priority)
