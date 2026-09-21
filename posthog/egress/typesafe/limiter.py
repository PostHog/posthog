"""TypeSafe egress budget keyed by the API credential's non-reversible fingerprint."""

import hashlib

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, per_minute_and_hourly_policy, register_policy

TYPESAFE_DOMAIN = "typesafe"

register_policy(
    TYPESAFE_DOMAIN,
    per_minute_and_hourly_policy(
        per_minute_setting="TYPESAFE_EGRESS_PER_MINUTE_BUDGET",
        per_minute_default=1_000,
        hourly_setting="TYPESAFE_EGRESS_HOURLY_BUDGET",
        hourly_default=50_000,
    ),
)


def typesafe_account_id(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def consume_typesafe_sync(account_id: str, *, priority: Priority = Priority.BATCH, source: str = "unknown") -> bool:
    return get_outbound_rate_limiter().consume_sync(
        f"{TYPESAFE_DOMAIN}:account:{account_id}",
        1,
        priority=priority,
        source=source,
    )
