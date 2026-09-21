from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, per_minute_and_hourly_policy, register_policy

register_policy(
    "typesafe",
    per_minute_and_hourly_policy(
        per_minute_setting="TYPESAFE_EGRESS_PER_MINUTE_BUDGET",
        per_minute_default=60,
        hourly_setting="TYPESAFE_EGRESS_HOURLY_BUDGET",
        hourly_default=1_000,
    ),
)


def consume_typesafe_sync(credential: str, *, priority: Priority, source: str) -> bool:
    return get_outbound_rate_limiter().consume_sync(
        f"typesafe:credential:{credential}", priority=priority, source=source
    )
