from django.test import SimpleTestCase, override_settings

from posthog.egress.limiter.policies import Priority, resolve_policy
from posthog.egress.ses.limiter import (
    SES_RECOMMENDATIONS_DOMAIN,
    pace_ses_recommendations_seconds,
    ses_recommendations_key,
)


class TestSesRecommendationsLimiter(SimpleTestCase):
    def test_the_key_resolves_to_a_registered_policy_that_reads_the_settings_budget(self) -> None:
        # A key whose domain has no policy raises at the first real call, and the only thing that
        # registers this one is importing the module, so a moved import breaks every SES caller.
        with override_settings(SES_REGION="eu-west-1", SES_RECOMMENDATIONS_EGRESS_PER_MINUTE_BUDGET=30):
            key = ses_recommendations_key()
            assert key == f"{SES_RECOMMENDATIONS_DOMAIN}:account:eu-west-1"
            assert resolve_policy(key).limits == ((30, 60.0),)

    def test_a_bulk_caller_is_always_told_to_wait_at_least_its_steady_interval(self) -> None:
        # The facade answers 0 while a window holds headroom and when its store is unreachable. The
        # sweep waits on this answer between teams, so a 0 would let it sprint through the quota.
        with override_settings(SES_RECOMMENDATIONS_EGRESS_PER_MINUTE_BUDGET=60):
            # 60 a minute less the 40% BATCH floor leaves 36, so a second spread over 36 calls.
            assert pace_ses_recommendations_seconds(priority=Priority.BATCH) >= 60.0 / 36
