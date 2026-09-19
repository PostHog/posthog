from django.conf import settings

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy

CLOUDFLARE_AI_DOMAIN = "cloudflare_ai"


def _policy(_key: str) -> RatePolicy:
    per_minute = int(getattr(settings, "SIGNALS_TYPESAFE_CLOUDFLARE_REQUESTS_PER_MINUTE", 20))
    return RatePolicy(limits=((per_minute, 60.0),), in_memory_divider=4)


register_policy(CLOUDFLARE_AI_DOMAIN, _policy)


async def acquire_cloudflare_ai(account_id: str, *, priority: Priority, source: str) -> bool:
    return await get_outbound_rate_limiter().acquire(
        f"{CLOUDFLARE_AI_DOMAIN}:account:{account_id}", priority=priority, source=source
    )
