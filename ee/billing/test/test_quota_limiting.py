from uuid import uuid4

from posthog.redis import get_client
from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from ee.billing.quota_limiting import RATE_LIMITER_CACHE_KEY, update_all_org_billing_quotas
from posthog.test.base import BaseTest, _create_event


class TestQuotaLimiting(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.redis_client = get_client()

    def test_billing_rate_limit_not_set_if_missing_org_usage(self) -> None:
        with self.settings(USE_TZ=False):
            self.organization.usage = {}
            self.organization.save()

            distinct_id = str(uuid4())

            # we add a bunch of events, so that the organization is over the limit, for events only, but not for recordings
            # however, since the organization has no usage set, we should not rate limit
            for _ in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=1),  # current day
                    team=self.team,
                )

        result = update_all_org_billing_quotas()
        assert result["events"] == {}
        assert result["recordings"] == {}

        assert self.redis_client.zrange(f"{RATE_LIMITER_CACHE_KEY}events", 0, -1) == []
        assert self.redis_client.zrange(f"{RATE_LIMITER_CACHE_KEY}recordings", 0, -1) == []

    def test_billing_rate_limit(self) -> None:
        with self.settings(USE_TZ=False):
            self.organization.usage = {"events": {"usage": 99, "limit": 100}, "recordings": {"usage": 1, "limit": 100}}
            self.organization.save()

            distinct_id = str(uuid4())

            # we add a bunch of events, so that the organization is over the limit
            # in this case the org has usage limits, so we want to rate limit for events, but not for recordings
            for _ in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=1),
                    team=self.team,
                )

        result = update_all_org_billing_quotas()
        org_id = str(self.organization.id)
        assert result["events"] == {org_id: now().timestamp()}
        assert result["recordings"] == {}

        assert self.redis_client.zrange(f"{RATE_LIMITER_CACHE_KEY}events", 0, -1) == [org_id.encode("UTF-8")]
        assert self.redis_client.zrange(f"{RATE_LIMITER_CACHE_KEY}recordings", 0, -1) == []
