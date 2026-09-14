"""Outbound Browserless budget, keyed by the fingerprint of the fleet's token.

Browserless meters concurrent sessions rather than requests, and a session is held for the whole
page load: a few seconds for a screenshot, tens of seconds for a Lighthouse audit. So the budget
below counts browser loads asked of one fleet, not API chatter, and the ceilings are small next
to a typical API budget.

The fleet is the unit because that is what actually runs out. Two callers pointed at one
Browserless draw from one pool of workers whatever team or product they serve, so keying on
anything narrower would let them each stay inside their own limit and still exhaust the fleet
between them. Callers pointed at separate fleets fingerprint differently and never interfere.
"""

from django.conf import settings

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy

BROWSERLESS_DOMAIN = "browserless"


def _browserless_policy(_key: str) -> RatePolicy:
    return RatePolicy(
        limits=(
            (int(getattr(settings, "BROWSERLESS_EGRESS_PER_MINUTE_BUDGET", 120)), 60.0),
            (int(getattr(settings, "BROWSERLESS_EGRESS_HOURLY_BUDGET", 2_000)), 3600.0),
        ),
        in_memory_divider=4,
    )


register_policy(BROWSERLESS_DOMAIN, _browserless_policy)


def consume_browserless_sync(scope: str, *, priority: Priority, source: str) -> bool:
    return get_outbound_rate_limiter().consume_sync(
        f"{BROWSERLESS_DOMAIN}:fleet:{scope}",
        priority=priority,
        source=source,
    )
