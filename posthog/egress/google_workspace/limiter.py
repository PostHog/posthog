from django.conf import settings

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy

GOOGLE_WORKSPACE_DOMAIN = "google_workspace"


def _google_workspace_policy(_key: str) -> RatePolicy:
    return RatePolicy(
        limits=(
            (int(getattr(settings, "GOOGLE_WORKSPACE_EGRESS_PER_MINUTE_BUDGET", 250)), 60.0),
            (int(getattr(settings, "GOOGLE_WORKSPACE_EGRESS_HOURLY_BUDGET", 10_000)), 3600.0),
        ),
        in_memory_divider=4,
    )


register_policy(GOOGLE_WORKSPACE_DOMAIN, _google_workspace_policy)


def consume_google_workspace_sync(account_id: str, *, priority: Priority, source: str) -> bool:
    return get_outbound_rate_limiter().consume_sync(
        f"{GOOGLE_WORKSPACE_DOMAIN}:account:{account_id}",
        priority=priority,
        source=source,
    )
