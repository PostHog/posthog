import time
from uuid import uuid4

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.utils.timezone import now
from freezegun import freeze_time

from ee.billing.quota_limiting import (
    QUOTA_LIMITER_CACHE_KEY,
    QuotaResource,
    list_limited_team_attributes,
    org_quota_limited_until,
    replace_limited_team_tokens,
    set_org_usage_summary,
    sync_org_quota_limits,
    update_all_org_billing_quotas,
)
from posthog.api.test.test_team import create_team
from posthog.redis import get_client
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
        assert result["rows_synced"] == {}

        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}events", 0, -1) == []
        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}recordings", 0, -1) == []
        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}rows_synced", 0, -1) == []

    def test_billing_rate_limit(self) -> None:
        with self.settings(USE_TZ=False):
            self.organization.usage = {
                "events": {"usage": 99, "limit": 100},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 5, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
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
        time.sleep(1)
        result = update_all_org_billing_quotas()
        org_id = str(self.organization.id)
        assert result["events"] == {org_id: 1612137599}
        assert result["recordings"] == {}
        assert result["rows_synced"] == {}

        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}events", 0, -1) == [
            self.team.api_token.encode("UTF-8")
        ]
        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}recordings", 0, -1) == []
        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}rows_synced", 0, -1) == []

        self.organization.refresh_from_db()
        assert self.organization.usage == {
            "events": {"usage": 99, "limit": 100, "todays_usage": 10},
            "recordings": {"usage": 1, "limit": 100, "todays_usage": 0},
            "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 0},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }

    def test_set_org_usage_summary_updates_correctly(self):
        self.organization.usage = {
            "events": {"usage": 99, "limit": 100},
            "recordings": {"usage": 1, "limit": 100},
            "rows_synced": {"usage": 5, "limit": 100},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.save()

        new_usage = dict(
            events={"usage": 100, "limit": 100},
            recordings={"usage": 2, "limit": 100},
            rows_synced={"usage": 6, "limit": 100},
            period=[
                "2021-01-01T00:00:00Z",
                "2021-01-31T23:59:59Z",
            ],
        )

        assert set_org_usage_summary(self.organization, new_usage=new_usage)

        assert self.organization.usage == {
            "events": {"usage": 100, "limit": 100, "todays_usage": 0},
            "recordings": {"usage": 2, "limit": 100, "todays_usage": 0},
            "rows_synced": {"usage": 6, "limit": 100, "todays_usage": 0},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }

    def test_set_org_usage_summary_does_nothing_if_the_same(self):
        self.organization.usage = {
            "events": {"usage": 99, "limit": 100, "todays_usage": 10},
            "recordings": {"usage": 1, "limit": 100, "todays_usage": 11},
            "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 11},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.save()

        new_usage = dict(
            events={"usage": 99, "limit": 100},
            recordings={"usage": 1, "limit": 100},
            rows_synced={"usage": 5, "limit": 100},
            period=[
                "2021-01-01T00:00:00Z",
                "2021-01-31T23:59:59Z",
            ],
        )

        assert not set_org_usage_summary(self.organization, new_usage=new_usage)

        assert self.organization.usage == {
            "events": {"usage": 99, "limit": 100, "todays_usage": 10},
            "recordings": {"usage": 1, "limit": 100, "todays_usage": 11},
            "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 11},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }

    def test_set_org_usage_summary_updates_todays_usage(self):
        self.organization.usage = {
            "events": {"usage": 99, "limit": 100, "todays_usage": 10},
            "recordings": {"usage": 1, "limit": 100, "todays_usage": 11},
            "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 11},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.save()

        assert set_org_usage_summary(
            self.organization, todays_usage={"events": 20, "recordings": 21, "rows_synced": 21}
        )

        assert self.organization.usage == {
            "events": {"usage": 99, "limit": 100, "todays_usage": 20},
            "recordings": {"usage": 1, "limit": 100, "todays_usage": 21},
            "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 21},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }

    def test_org_quota_limited_until(self):
        self.organization.usage = None
        assert org_quota_limited_until(self.organization, QuotaResource.EVENTS) is None

        self.organization.usage = {
            "events": {"usage": 99, "limit": 100},
            "recordings": {"usage": 1, "limit": 100},
            "rows_synced": {"usage": 99, "limit": 100},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }

        assert org_quota_limited_until(self.organization, QuotaResource.EVENTS) is None

        self.organization.usage["events"]["usage"] = 120
        assert org_quota_limited_until(self.organization, QuotaResource.EVENTS) == 1612137599

        self.organization.usage["events"]["usage"] = 90
        self.organization.usage["events"]["todays_usage"] = 10
        assert org_quota_limited_until(self.organization, QuotaResource.EVENTS) == 1612137599

        self.organization.usage["events"]["limit"] = None
        assert org_quota_limited_until(self.organization, QuotaResource.EVENTS) is None

        self.organization.usage["recordings"]["usage"] = 1099  # Under limit + buffer
        assert org_quota_limited_until(self.organization, QuotaResource.RECORDINGS) is None

        self.organization.usage["recordings"]["usage"] = 1100  # Over limit + buffer
        assert org_quota_limited_until(self.organization, QuotaResource.RECORDINGS) == 1612137599

        assert org_quota_limited_until(self.organization, QuotaResource.ROWS_SYNCED) is None

        self.organization.usage["rows_synced"]["usage"] = 101
        assert org_quota_limited_until(self.organization, QuotaResource.ROWS_SYNCED) == 1612137599

    def test_over_quota_but_not_dropped_org(self):
        self.organization.usage = None
        assert org_quota_limited_until(self.organization, QuotaResource.EVENTS) is None

        self.organization.usage = {
            "events": {"usage": 100, "limit": 90},
            "recordings": {"usage": 100, "limit": 90},
            "rows_synced": {"usage": 100, "limit": 90},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.never_drop_data = True

        assert org_quota_limited_until(self.organization, QuotaResource.EVENTS) is None
        assert org_quota_limited_until(self.organization, QuotaResource.RECORDINGS) is None
        assert org_quota_limited_until(self.organization, QuotaResource.ROWS_SYNCED) is None

        # reset for subsequent tests
        self.organization.never_drop_data = False

    def test_sync_org_quota_limits(self):
        with freeze_time("2021-01-01T12:59:59Z"):
            other_team = create_team(organization=self.organization)

            now = timezone.now().timestamp()

            replace_limited_team_tokens(QuotaResource.EVENTS, {"1234": now + 10000})
            replace_limited_team_tokens(QuotaResource.ROWS_SYNCED, {"1337": now + 10000})
            self.organization.usage = {
                "events": {"usage": 99, "limit": 100},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 35, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }

            sync_org_quota_limits(self.organization)
            assert list_limited_team_attributes(QuotaResource.EVENTS) == ["1234"]
            assert list_limited_team_attributes(QuotaResource.ROWS_SYNCED) == ["1337"]

            self.organization.usage["events"]["usage"] = 120
            self.organization.usage["rows_synced"]["usage"] = 120
            sync_org_quota_limits(self.organization)
            assert sorted(list_limited_team_attributes(QuotaResource.EVENTS)) == sorted(
                ["1234", self.team.api_token, other_team.api_token]
            )

            # rows_synced uses teams, not tokens
            assert sorted(list_limited_team_attributes(QuotaResource.ROWS_SYNCED)) == sorted(
                ["1337", str(self.team.pk), str(other_team.pk)]
            )

            self.organization.usage["events"]["usage"] = 80
            self.organization.usage["rows_synced"]["usage"] = 36
            sync_org_quota_limits(self.organization)
            assert sorted(list_limited_team_attributes(QuotaResource.EVENTS)) == sorted(["1234"])
            assert sorted(list_limited_team_attributes(QuotaResource.ROWS_SYNCED)) == sorted(["1337"])
