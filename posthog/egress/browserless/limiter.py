"""Outbound Browserless budget, keyed by the fleet a call competes for.

Browserless meters concurrent sessions rather than requests, and a session is held for the whole
page load: a few seconds for a screenshot, tens of seconds for a Lighthouse audit. So the budget
below counts browser loads asked of one fleet, not API chatter, and the ceilings are small next
to a typical API budget.

The fleet is the unit because that is what actually runs out. Two callers pointed at one
Browserless draw from one pool of workers whatever team or product they serve, so keying on
anything narrower would let them each stay inside their own limit and still exhaust the fleet
between them. Callers pointed at separate fleets fingerprint differently and never interfere.

The default reserve ladder applies, because the callers differ sharply in urgency: a ``BATCH``
background load is shed before a ``NORMAL`` render that somebody is waiting on.
"""

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, per_minute_and_hourly_policy, register_policy

BROWSERLESS_DOMAIN = "browserless"

register_policy(
    BROWSERLESS_DOMAIN,
    per_minute_and_hourly_policy(
        per_minute_setting="BROWSERLESS_EGRESS_PER_MINUTE_BUDGET",
        per_minute_default=120,
        hourly_setting="BROWSERLESS_EGRESS_HOURLY_BUDGET",
        hourly_default=2_000,
    ),
)


def consume_browserless_sync(scope: str, *, priority: Priority, source: str) -> bool:
    return get_outbound_rate_limiter().consume_sync(
        f"{BROWSERLESS_DOMAIN}:fleet:{scope}",
        priority=priority,
        source=source,
    )
