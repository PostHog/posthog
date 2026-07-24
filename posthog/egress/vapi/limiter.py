"""Outbound Vapi API budget keyed by the configured API token fingerprint."""

from django.conf import settings

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy

VAPI_DOMAIN = "vapi"


def _vapi_policy(_key: str) -> RatePolicy:
    return RatePolicy(
        limits=(
            (int(getattr(settings, "VAPI_EGRESS_PER_MINUTE_BUDGET", 10_000)), 60.0),
            (int(getattr(settings, "VAPI_EGRESS_HOURLY_BUDGET", 100_000)), 3600.0),
        ),
        in_memory_divider=4,
    )


register_policy(VAPI_DOMAIN, _vapi_policy)


def consume_vapi_api_sync(scope: str, *, priority: Priority, source: str) -> bool:
    return get_outbound_rate_limiter().consume_sync(
        f"{VAPI_DOMAIN}:api_key:{scope}",
        priority=priority,
        source=source,
    )
