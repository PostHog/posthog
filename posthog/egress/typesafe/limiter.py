"""TypeSafe egress budget.

TypeSafe meters per API key and bills per input token. A PostHog instance holds a single TypeSafe
API key, so the whole instance draws from one shared budget under a constant scope. TypeSafe
publishes 1,200 requests per minute for the key, so the per-minute default sits under that and the
hourly default is an operator ceiling on spend.

Importing this module registers the policy as a side effect, so import it (directly or via
``consume_typesafe_sync``) before using a ``typesafe:...`` limiter key.
"""

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, per_minute_and_hourly_policy, register_policy

TYPESAFE_DOMAIN = "typesafe"

# One TypeSafe API key per instance, so a constant id carries the instance-wide shared budget.
ACCOUNT_SCOPE_ID = "default"

# Nothing in this domain runs CRITICAL: the state Jev classifies comes from user-supplied text, and
# every caller can do without the suggestion, so a never-shed lane would make the budget advisory.
register_policy(
    TYPESAFE_DOMAIN,
    per_minute_and_hourly_policy(
        per_minute_setting="TYPESAFE_EGRESS_PER_MINUTE_BUDGET",
        per_minute_default=600,
        hourly_setting="TYPESAFE_EGRESS_HOURLY_BUDGET",
        hourly_default=10_000,
    ),
)


def typesafe_account_key() -> str:
    """Limiter key for the instance's single TypeSafe API key, which is the unit TypeSafe meters."""
    return f"{TYPESAFE_DOMAIN}:account:{ACCOUNT_SCOPE_ID}"


def consume_typesafe_sync(n: int = 1, *, priority: Priority = Priority.NORMAL, source: str = "unknown") -> bool:
    """Reserve ``n`` requests against the instance's TypeSafe budget. Returns False when the budget
    (or this ``priority``'s reserved floor) is exhausted, so degrade gracefully rather than calling out."""
    return get_outbound_rate_limiter().consume_sync(typesafe_account_key(), n, priority=priority, source=source)
