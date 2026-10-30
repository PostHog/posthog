"""Cloudflare egress budget.

Cloudflare limits API calls per user or token, and meters cache purges per account. A PostHog
instance holds one purge token, so the whole instance draws from one shared budget under a constant
scope. The defaults sit far below Cloudflare's documented limits: they stop a runaway caller from
locking the token out of the API for five minutes, which is what Cloudflare does after a 429.

Importing this module registers the policy as a side effect, so import it (directly or via
``consume_cloudflare_sync``) before using a ``cloudflare:...`` limiter key.
"""

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, per_minute_and_hourly_policy, register_policy

CLOUDFLARE_DOMAIN = "cloudflare"

ACCOUNT_SCOPE_ID = "default"

# Operator ceilings, not provider limits. Cloudflare allows 1,200 requests per five minutes per
# token, and every caller so far is a staff action that purges a few URLs at a time.
register_policy(
    CLOUDFLARE_DOMAIN,
    per_minute_and_hourly_policy(
        per_minute_setting="CLOUDFLARE_EGRESS_PER_MINUTE_BUDGET",
        per_minute_default=30,
        hourly_setting="CLOUDFLARE_EGRESS_HOURLY_BUDGET",
        hourly_default=300,
    ),
)


def cloudflare_account_key() -> str:
    """Limiter key for the instance's single Cloudflare token."""
    return f"{CLOUDFLARE_DOMAIN}:account:{ACCOUNT_SCOPE_ID}"


def consume_cloudflare_sync(n: int = 1, *, priority: Priority = Priority.NORMAL, source: str = "unknown") -> bool:
    """Reserve ``n`` requests against the instance's Cloudflare budget. Returns False when the budget
    (or this ``priority``'s reserved floor) is exhausted, so degrade gracefully rather than calling out."""
    return get_outbound_rate_limiter().consume_sync(cloudflare_account_key(), n, priority=priority, source=source)
