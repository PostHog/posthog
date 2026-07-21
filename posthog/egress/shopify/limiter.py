"""Shopify egress budget.

PostHog talks to a single Shopify store (the merch store, ``settings.SHOPIFY_MERCH_STORE_DOMAIN``)
to mint discount codes, so the whole instance draws from one shared budget under a constant scope.
The calls are staff-triggered and low-frequency, so the defaults are modest operator ceilings rather
than an observed provider limit.

Importing this module registers the policy as a side effect — import it (directly or via
``consume_shopify_sync``) before using a ``shopify:...`` limiter key.
"""

from django.conf import settings

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy

SHOPIFY_DOMAIN = "shopify"

# One merch store per instance — the constant id for the instance-wide shared budget.
_STORE_SCOPE_ID = "default"

# Same reserved-floor ladder as the other egress domains: BATCH is denied first as the budget fills.
# Merch mints run CRITICAL (an explicit staff action), so they draw on the whole budget and are never
# shed; the reserve only shapes any future non-critical Shopify traffic.
_RESERVE: dict[Priority, float] = {Priority.BATCH: 0.30, Priority.NORMAL: 0.10}

# Operator ceilings for a staff-triggered, low-frequency mint — generous enough to never bite normal
# use, low enough to cap a runaway loop.
_DEFAULT_PER_MINUTE_BUDGET = 30
_DEFAULT_HOURLY_BUDGET = 200


# Registered as a provider so the budgets are read at acquire time — a settings override applies
# without a process restart, matching the other egress domains.
def _shopify_policy(key: str) -> RatePolicy:
    per_minute = int(getattr(settings, "SHOPIFY_EGRESS_PER_MINUTE_BUDGET", _DEFAULT_PER_MINUTE_BUDGET))
    hourly = int(getattr(settings, "SHOPIFY_EGRESS_HOURLY_BUDGET", _DEFAULT_HOURLY_BUDGET))
    return RatePolicy(
        limits=((per_minute, 60.0), (hourly, 3600.0)),
        in_memory_divider=4,
        reserve=_RESERVE,
    )


register_policy(SHOPIFY_DOMAIN, _shopify_policy)


def shopify_store_key() -> str:
    """Limiter key for the instance's single Shopify store — the unit we budget."""
    return f"{SHOPIFY_DOMAIN}:store:{_STORE_SCOPE_ID}"


def consume_shopify_sync(n: int = 1, *, priority: Priority = Priority.CRITICAL, source: str = "unknown") -> bool:
    """Reserve ``n`` requests against the instance's Shopify budget. Returns False when the budget is
    exhausted. Merch mints pass CRITICAL, so they are admitted unless the whole budget is spent."""
    return get_outbound_rate_limiter().consume_sync(shopify_store_key(), n, priority=priority, source=source)
