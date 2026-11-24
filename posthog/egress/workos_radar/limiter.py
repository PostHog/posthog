"""WorkOS Radar egress budget for success reports.

WorkOS allows each API key 1,000 requests per 60 seconds on ``/radar/*``, and an instance holds a
single Radar key, so the budget uses a constant scope. Only the success reports draw from it. A
check is never gated, because a shed check lets the attempt through, and a flood of logins could
then turn Radar off. The report budget is a share of the WorkOS limit, so a burst of reports always
leaves room for the checks.

The reports are the only gated caller, so the policy is flat: no higher lane needs a reserve.

Importing this module registers the policy as a side effect, so import it (directly or via
``consume_workos_radar_report_sync``) before using a ``workos_radar:...`` limiter key.
"""

from django.conf import settings

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy

WORKOS_RADAR_DOMAIN = "workos_radar"

API_KEY_SCOPE_ID = "default"


def _report_policy(_key: str) -> RatePolicy:
    # A value under 1 would make the limiter refuse every report instead of pacing them
    per_minute = max(1, int(settings.WORKOS_RADAR_REPORT_EGRESS_PER_MINUTE_BUDGET))
    # Without Redis each process admits one report a minute, because no process knows how many others run
    return RatePolicy(limits=((per_minute, 60.0),), in_memory_divider=per_minute, reserve={})


register_policy(WORKOS_RADAR_DOMAIN, _report_policy)


def workos_radar_key() -> str:
    """Limiter key for the instance's single Radar API key, which is the unit WorkOS meters."""
    return f"{WORKOS_RADAR_DOMAIN}:api_key:{API_KEY_SCOPE_ID}"


def consume_workos_radar_report_sync(*, source: str) -> bool:
    """Reserve one success report against the report budget. Returns False when the budget is spent."""
    return get_outbound_rate_limiter().consume_sync(workos_radar_key(), 1, priority=Priority.BATCH, source=source)
