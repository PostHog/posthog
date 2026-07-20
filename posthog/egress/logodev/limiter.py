"""logo.dev egress budget.

logo.dev meters usage per account token, and each PostHog instance holds exactly one
(``settings.LOGO_DEV_TOKEN``), so the whole instance draws from a single shared budget under a
constant scope. logo.dev publishes no hard rate-limit numbers, so the defaults are deliberately
modest operator ceilings — icon responses are cached for a day by the consumer
(:mod:`posthog.cdp.services.icons`), so steady-state traffic sits far below them.

Importing this module registers the policy as a side effect — import it (directly or via
``consume_logodev_sync``) before using a ``logodev:...`` limiter key.
"""

from django.conf import settings

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy

LOGODEV_DOMAIN = "logodev"

# One account per instance — the constant id for the instance-wide shared budget.
_ACCOUNT_SCOPE_ID = "default"

# Same reserved-floor ladder as the other egress domains: sheddable lanes are denied first as the
# budget fills, CRITICAL (user-facing icon renders) may use the full budget.
_RESERVE: dict[Priority, float] = {Priority.BATCH: 0.30, Priority.NORMAL: 0.10}

# Operator ceilings, not observed provider limits (logo.dev exposes none to observe). The per-minute
# rate smooths bursts (a catalog page fanning out cache misses), the hourly rate caps total spend.
_DEFAULT_PER_MINUTE_BUDGET = 300
_DEFAULT_HOURLY_BUDGET = 5_000


# Registered as a provider so the budgets are read at acquire time — a settings override applies
# without a process restart, matching the other egress domains.
def _logodev_policy(key: str) -> RatePolicy:
    per_minute = int(getattr(settings, "LOGODEV_EGRESS_PER_MINUTE_BUDGET", _DEFAULT_PER_MINUTE_BUDGET))
    hourly = int(getattr(settings, "LOGODEV_EGRESS_HOURLY_BUDGET", _DEFAULT_HOURLY_BUDGET))
    return RatePolicy(
        limits=((per_minute, 60.0), (hourly, 3600.0)),
        in_memory_divider=4,
        reserve=_RESERVE,
    )


register_policy(LOGODEV_DOMAIN, _logodev_policy)


def logodev_account_key() -> str:
    """Limiter key for the instance's single logo.dev account — the unit logo.dev meters."""
    return f"{LOGODEV_DOMAIN}:account:{_ACCOUNT_SCOPE_ID}"


def consume_logodev_sync(n: int = 1, *, priority: Priority = Priority.NORMAL, source: str = "unknown") -> bool:
    """Reserve ``n`` requests against the instance's logo.dev budget. Returns False when the budget
    (or this ``priority``'s reserved floor) is exhausted — degrade gracefully rather than calling out."""
    return get_outbound_rate_limiter().consume_sync(logodev_account_key(), n, priority=priority, source=source)
