"""TypeSafe egress budget.

A PostHog instance's TypeSafe API key draws from one shared budget under a constant scope.
Caller-owned credentials and compatible endpoints use separate fingerprinted scopes.
The per-minute default stays at half of TypeSafe's published request
limit, because TypeSafe changes its limits without notice. The hourly default is an operator ceiling
on spend, because TypeSafe bills every input token.

Importing this module registers the policy as a side effect, so import it (directly or via
``consume_typesafe_sync``) before using a ``typesafe:...`` limiter key.
"""

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, per_minute_and_hourly_policy, register_policy

TYPESAFE_DOMAIN = "typesafe"

ACCOUNT_SCOPE_ID = "default"

register_policy(
    TYPESAFE_DOMAIN,
    per_minute_and_hourly_policy(
        per_minute_setting="TYPESAFE_EGRESS_PER_MINUTE_BUDGET",
        per_minute_default=600,
        hourly_setting="TYPESAFE_EGRESS_HOURLY_BUDGET",
        hourly_default=20_000,
    ),
)


def typesafe_account_key(scope: str = ACCOUNT_SCOPE_ID) -> str:
    return f"{TYPESAFE_DOMAIN}:account:{scope}"


def consume_typesafe_sync(
    n: int = 1, *, scope: str = ACCOUNT_SCOPE_ID, priority: Priority = Priority.NORMAL, source: str = "unknown"
) -> bool:
    """Reserve ``n`` requests against the scope's TypeSafe budget. Returns False when the budget
    (or this ``priority``'s reserved floor) is exhausted, so degrade gracefully rather than calling out."""
    return get_outbound_rate_limiter().consume_sync(typesafe_account_key(scope), n, priority=priority, source=source)
