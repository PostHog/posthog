"""SES ListRecommendations egress budget.

AWS meters SESv2 ``ListRecommendations`` account-wide, and it is the tightest quota any SES caller
here touches: roughly one request per second, against operations like ``GetTenant`` that answer far
faster. Three callers share it — the account reputation poller, the daily tenant reconciliation
sweep, and the Reputation tab in the app. The sweep is the only one big enough to spend the whole
quota on its own, so it takes the sheddable lane and the other two keep a reserved floor.

Importing this module registers the policy as a side effect, so import it (directly or via
``consume_ses_recommendations_sync``) before using a ``ses_recommendations:...`` limiter key.
"""

from django.conf import settings

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy
from posthog.egress.transport.transport import EgressBudgetExhausted

SES_RECOMMENDATIONS_DOMAIN = "ses_recommendations"

# The quota belongs to the SES account in one region, which is what AWS meters. A deployment holds
# one set of SES credentials, so the region names that account without the STS call an account id
# would cost on every gate.
_SCOPE = "account"

# Only the reconciliation sweep is sheddable. The poller feeds the gauges the SES alerts evaluate
# and the Reputation tab serves a person waiting on a response, and both spend a handful of calls,
# so denying either would cost a real answer to save budget they cannot dent.
_RESERVE: dict[Priority, float] = {Priority.BATCH: 0.40}

# Under AWS's own ceiling of about 60 calls a minute, so botocore's retries absorb the drift our
# own counter cannot see: clock skew, races between worker processes, and the SES console.
_DEFAULT_PER_MINUTE_BUDGET = 45

# The fallback counts one process rather than the shared budget. It is left undivided because the
# consumer that can exhaust this quota is a single sweep running in one process at a time, and
# shrinking its fallback share would turn a Redis outage into a sweep that reconciles almost
# nothing. The callers that do run in many processes each spend a few calls, and botocore's
# adaptive retries remain the backstop.
_IN_MEMORY_DIVIDER = 1


class SESRecommendationsBudgetExhausted(EgressBudgetExhausted):
    """A sheddable ListRecommendations call was denied before it was sent, so our own shared budget
    is spent rather than SES having refused the call."""


def _ses_recommendations_policy(_key: str) -> RatePolicy:
    per_minute = int(getattr(settings, "SES_RECOMMENDATIONS_EGRESS_PER_MINUTE_BUDGET", _DEFAULT_PER_MINUTE_BUDGET))
    return RatePolicy(limits=((per_minute, 60.0),), in_memory_divider=_IN_MEMORY_DIVIDER, reserve=_RESERVE)


register_policy(SES_RECOMMENDATIONS_DOMAIN, _ses_recommendations_policy)


def ses_recommendations_key() -> str:
    """Limiter key for the SES account whose ListRecommendations quota every caller draws on."""
    return f"{SES_RECOMMENDATIONS_DOMAIN}:{_SCOPE}:{settings.SES_REGION}"


def consume_ses_recommendations_sync(
    n: int = 1, *, priority: Priority = Priority.NORMAL, source: str = "unknown"
) -> bool:
    """Reserve ``n`` ListRecommendations calls against the account budget. Returns False when the
    budget (or this priority's reserved floor) is spent, so the caller decides whether to shed."""
    return get_outbound_rate_limiter().consume_sync(ses_recommendations_key(), n, priority=priority, source=source)


def pace_ses_recommendations_seconds(*, priority: Priority = Priority.BATCH) -> float:
    """Seconds a bulk caller should wait before its next ListRecommendations call.

    Always positive, unlike the facade's own ``pace_seconds``. That answers 0 both while a window
    still holds headroom and when the limiter store is unreachable, which suits a caller short
    enough never to spend its share. A caller that walks every team spends the whole window either
    way, so it holds a steady interval of its own and lets contention slow it further.
    """
    key = ses_recommendations_key()
    policy = _ses_recommendations_policy(key)
    count, period = policy.limits[0]
    allowance = max(1, count - policy.reserve_amount(priority, count))
    return max(get_outbound_rate_limiter().pace_seconds(key, priority=priority), period / allowance)
