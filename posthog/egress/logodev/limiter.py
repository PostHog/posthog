"""logo.dev egress budget.

logo.dev meters usage per account, and each PostHog instance configures the image and Search API
credentials from that account, so the whole instance draws from a single shared budget under a
constant scope. logo.dev limits requests per month by plan, with no per-minute or hourly limit, so
the defaults are deliberately modest operator ceilings. Icon bytes are never stored server-side (logo.dev gates that behind a
data-caching license), so upstream volume is deduped only per user, by the browser caching that
:mod:`posthog.cdp.services.icons` directs — steady-state traffic tracks unique (user, icon) first
views per day. Raise the settings below if that outgrows the defaults.

Importing this module registers the policy as a side effect — import it (directly or via
``consume_logodev_sync``) before using a ``logodev:...`` limiter key.
"""

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, per_minute_and_hourly_policy, register_policy

LOGODEV_DOMAIN = "logodev"

# One account per instance — the constant id for the instance-wide shared budget.
ACCOUNT_SCOPE_ID = "default"

# Operator ceilings, not observed provider limits (logo.dev exposes none to observe). The per-minute
# rate smooths bursts (a catalog page fanning out cache misses), the hourly rate caps total spend.
# All icon traffic runs NORMAL — the icon id is user-controlled, so nothing in this domain should run
# CRITICAL (a never-shed lane would make the budget advisory).
register_policy(
    LOGODEV_DOMAIN,
    per_minute_and_hourly_policy(
        per_minute_setting="LOGODEV_EGRESS_PER_MINUTE_BUDGET",
        per_minute_default=300,
        hourly_setting="LOGODEV_EGRESS_HOURLY_BUDGET",
        hourly_default=5_000,
    ),
)


def logodev_account_key() -> str:
    """Limiter key for the instance's single logo.dev account — the unit logo.dev meters."""
    return f"{LOGODEV_DOMAIN}:account:{ACCOUNT_SCOPE_ID}"


def consume_logodev_sync(n: int = 1, *, priority: Priority = Priority.NORMAL, source: str = "unknown") -> bool:
    """Reserve ``n`` requests against the instance's logo.dev budget. Returns False when the budget
    (or this ``priority``'s reserved floor) is exhausted — degrade gracefully rather than calling out."""
    return get_outbound_rate_limiter().consume_sync(logodev_account_key(), n, priority=priority, source=source)
