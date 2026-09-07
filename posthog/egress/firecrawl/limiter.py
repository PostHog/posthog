"""Firecrawl egress budget.

Firecrawl meters per account and bills credits per call, and a PostHog instance holds a single
Firecrawl API key, so the whole instance draws from one shared budget under a constant scope.
Firecrawl's per-plan request limits are not discoverable from the running process, so the defaults
below are operator ceilings on spend rather than observed provider limits: they exist to stop a
retry loop or a burst of sign-ups from spending a plan's credits, not to mirror Firecrawl's own
limit. Raise them in settings when real traffic outgrows them.

Importing this module registers the policy as a side effect, so import it (directly or via
``consume_firecrawl_sync``) before using a ``firecrawl:...`` limiter key.
"""

from django.conf import settings

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy

FIRECRAWL_DOMAIN = "firecrawl"

# One Firecrawl account per instance, so a constant id carries the instance-wide shared budget.
_ACCOUNT_SCOPE_ID = "default"

# Same reserved-floor ladder as the other egress domains: BATCH is denied first as the budget fills,
# then NORMAL. Nothing in this domain runs CRITICAL, because the scraped URL is derived from
# user-supplied input and a never-shed lane would make the budget advisory.
_RESERVE: dict[Priority, float] = {Priority.BATCH: 0.30, Priority.NORMAL: 0.10}

# Operator ceilings on credit spend, not observed provider limits. Each scrape costs a credit, so
# the per-minute rate smooths a burst of concurrent sign-ups and the hourly rate caps what a runaway
# caller can spend before someone notices.
_DEFAULT_PER_MINUTE_BUDGET = 60
_DEFAULT_HOURLY_BUDGET = 1_000


# Registered as a provider so the budgets are read at acquire time, which means a settings override applies
# without a process restart, matching the other egress domains.
def _firecrawl_policy(key: str) -> RatePolicy:
    per_minute = int(getattr(settings, "FIRECRAWL_EGRESS_PER_MINUTE_BUDGET", _DEFAULT_PER_MINUTE_BUDGET))
    hourly = int(getattr(settings, "FIRECRAWL_EGRESS_HOURLY_BUDGET", _DEFAULT_HOURLY_BUDGET))
    return RatePolicy(
        limits=((per_minute, 60.0), (hourly, 3600.0)),
        in_memory_divider=4,
        reserve=_RESERVE,
    )


register_policy(FIRECRAWL_DOMAIN, _firecrawl_policy)


def firecrawl_account_key() -> str:
    """Limiter key for the instance's single Firecrawl account, which is the unit Firecrawl meters."""
    return f"{FIRECRAWL_DOMAIN}:account:{_ACCOUNT_SCOPE_ID}"


def consume_firecrawl_sync(n: int = 1, *, priority: Priority = Priority.NORMAL, source: str = "unknown") -> bool:
    """Reserve ``n`` requests against the instance's Firecrawl budget. Returns False when the budget
    (or this ``priority``'s reserved floor) is exhausted, so degrade gracefully rather than calling out."""
    return get_outbound_rate_limiter().consume_sync(firecrawl_account_key(), n, priority=priority, source=source)
