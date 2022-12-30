from unittest.mock import MagicMock, patch
from uuid import uuid4

import fakeredis
from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.tasks.billing_rate_limit import RATE_LIMITER_CACHE_KEY, update_all_org_billing_rate_limiting
from posthog.test.base import BaseTest, _create_event


@freeze_time("2022-01-10T02:01:00Z")
class TestBillingRateLimit(BaseTest):
    def setUp(self) -> None:
        self.redis_client = fakeredis.FakeStrictRedis()

    @patch("posthog.tasks.billing_rate_limit.get_client")
    def test_billing_rate_limit_not_set_if_missing_org_usage(self, mock_redis_client: MagicMock) -> None:
        mock_redis_client.return_value = self.redis_client
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

        result = update_all_org_billing_rate_limiting()
        assert result["events"] == {}
        assert result["recordings"] == {}

        assert self.redis_client.zrange(f"{RATE_LIMITER_CACHE_KEY}events", 0, -1) == []
        assert self.redis_client.zrange(f"{RATE_LIMITER_CACHE_KEY}recordings", 0, -1) == []

    @patch("posthog.tasks.billing_rate_limit.get_client")
    def test_billing_rate_limit(self, mock_redis_client: MagicMock) -> None:
        mock_redis_client.return_value = self.redis_client
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

        result = update_all_org_billing_rate_limiting()
        org_id = str(self.organization.id)
        assert result["events"] == {org_id: now().timestamp()}
        assert result["recordings"] == {}

        assert self.redis_client.zrange(f"{RATE_LIMITER_CACHE_KEY}events", 0, -1) == [org_id.encode("UTF-8")]
        assert self.redis_client.zrange(f"{RATE_LIMITER_CACHE_KEY}recordings", 0, -1) == []
