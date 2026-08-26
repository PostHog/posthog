from django.conf import settings

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy

PUBLIC_WEB_DOMAIN = "public_web"

_RESERVE: dict[Priority, float] = {Priority.BATCH: 0.30, Priority.NORMAL: 0.10}
_DEFAULT_PER_MINUTE_BUDGET = 30
_DEFAULT_HOURLY_BUDGET = 300


def _public_web_policy(key: str) -> RatePolicy:
    per_minute = int(getattr(settings, "PUBLIC_WEB_EGRESS_PER_MINUTE_BUDGET", _DEFAULT_PER_MINUTE_BUDGET))
    hourly = int(getattr(settings, "PUBLIC_WEB_EGRESS_HOURLY_BUDGET", _DEFAULT_HOURLY_BUDGET))
    return RatePolicy(
        limits=((per_minute, 60.0), (hourly, 3600.0)),
        in_memory_divider=4,
        reserve=_RESERVE,
    )


register_policy(PUBLIC_WEB_DOMAIN, _public_web_policy)


def consume_public_web_sync(
    hostname: str, n: int = 1, *, priority: Priority = Priority.NORMAL, source: str = "unknown"
) -> bool:
    key = f"{PUBLIC_WEB_DOMAIN}:host:{hostname.lower()}"
    return get_outbound_rate_limiter().consume_sync(key, n, priority=priority, source=source)
