"""WorkOS Radar egress budget.

WorkOS meters the Radar API per API key, and an instance holds a single Radar key, so the whole
instance draws from one shared budget under a constant scope. WorkOS allows 1,000 requests per 60
seconds on ``/radar/*``. The default budget stays under that, so a burst of checks meets our limiter
before it meets WorkOS's 429.

Importing this module registers the policy as a side effect, so import it (directly or via
``consume_workos_radar_sync``) before using a ``workos_radar:...`` limiter key.
"""

from django.conf import settings

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy

WORKOS_RADAR_DOMAIN = "workos_radar"

# One Radar API key per instance, so a constant id carries the instance-wide shared budget.
API_KEY_SCOPE_ID = "default"


def _radar_policy(_key: str) -> RatePolicy:
    # WorkOS documents a 60-second limit and no hourly one, so the policy has one window.
    # The default reserve applies: success reports run BATCH and are shed before the checks
    # that a person waits on, which run NORMAL.
    return RatePolicy(
        limits=((int(settings.WORKOS_RADAR_EGRESS_PER_MINUTE_BUDGET), 60.0),),
        in_memory_divider=4,
    )


register_policy(WORKOS_RADAR_DOMAIN, _radar_policy)


def workos_radar_key() -> str:
    """Limiter key for the instance's single Radar API key, which is the unit WorkOS meters."""
    return f"{WORKOS_RADAR_DOMAIN}:api_key:{API_KEY_SCOPE_ID}"


def consume_workos_radar_sync(n: int = 1, *, priority: Priority, source: str) -> bool:
    """Reserve ``n`` requests against the instance's Radar budget. Returns False when the budget
    (or this ``priority``'s reserved floor) is exhausted."""
    return get_outbound_rate_limiter().consume_sync(workos_radar_key(), n, priority=priority, source=source)
