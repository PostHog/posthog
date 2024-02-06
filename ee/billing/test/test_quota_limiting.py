import time
from uuid import uuid4

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.utils.timezone import now
from freezegun import freeze_time

from ee.billing.quota_limiting import (
    QUOTA_LIMITER_CACHE_KEY,
    QUOTA_OVERAGE_RETENTION_CACHE_KEY,
    QuotaResource,
    determine_org_quota_limit_or_data_retention,
    list_limited_team_attributes,
    replace_limited_team_tokens,
    set_org_usage_summary,
    sync_org_quota_limits,
    update_all_org_billing_quotas,
)
from posthog.api.test.test_team import create_team
from posthog.redis import get_client
from posthog.test.base import BaseTest, _create_event


class TestQuotaLimiting(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.redis_client = get_client()
        self.redis_client.delete("QUOTA_OVERAGE_RETENTION_CACHE_KEYevents")
        self.redis_client.delete("QUOTA_OVERAGE_RETENTION_CACHE_KEYrecordings")
        self.redis_client.delete("QUOTA_OVERAGE_RETENTION_CACHE_KEYrows_synced")

    @patch("posthoganalytics.capture")
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_dont_quota_limit_feature_flag_enabled(self, patch_feature_enabled, patch_capture) -> None:
        with self.settings(USE_TZ=False):
            self.organization.usage = {
                "events": {"usage": 99, "limit": 100},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 5, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()

            distinct_id = str(uuid4())

            # add a bunch of events so that the organization is over the limit
            # Because the feature flag is enabled
            for _ in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=1),
                    team=self.team,
                )
        time.sleep(1)
        quota_limited_orgs, data_retained_orgs = update_all_org_billing_quotas()
        patch_feature_enabled.assert_called_with(
            QUOTA_LIMIT_DATA_RETENTION_FLAG,
            self.organization.id,
            groups={"organization": str(self.organization.id)},
            group_properties={"organization": {"id": str(self.organization.id)}},
        )
        patch_capture.assert_called_once_with(
            str(self.organization.id),
            "quota limiting suspended",
            properties={"current_usage": 109},
            groups={"instance": "http://localhost:8000", "organization": str(self.organization.id)},
        )
        assert data_retained_orgs["events"] == {}
        assert data_retained_orgs["recordings"] == {}
        assert data_retained_orgs["rows_synced"] == {}
        assert quota_limited_orgs["events"] == {}
        assert quota_limited_orgs["recordings"] == {}
        assert quota_limited_orgs["rows_synced"] == {}

        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}events", 0, -1) == []
        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}recordings", 0, -1) == []
        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}rows_synced", 0, -1) == []

    @patch("posthoganalytics.capture")
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_quota_limit_feature_flag_not_on(self, patch_feature_enabled, patch_capture) -> None:
        # Confirm that we don't send an event if they weren't going to be limited.
        self.organization.usage = {
            "events": {"usage": 99, "limit": 100},
            "recordings": {"usage": 1, "limit": 100},
            "rows_synced": {"usage": 5, "limit": 100},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.save()

        time.sleep(1)
        quota_limited_orgs, data_retained_orgs = update_all_org_billing_quotas()
        # Shouldn't be called due to lazy evaluation of the conditional
        patch_feature_enabled.assert_not_called()
        patch_capture.assert_not_called()
        assert data_retained_orgs["events"] == {}
        assert data_retained_orgs["recordings"] == {}
        assert data_retained_orgs["rows_synced"] == {}
        assert quota_limited_orgs["events"] == {}
        assert quota_limited_orgs["recordings"] == {}
        assert quota_limited_orgs["rows_synced"] == {}

        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}events", 0, -1) == []
        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}recordings", 0, -1) == []
        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}rows_synced", 0, -1) == []

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

        quota_limited_orgs, data_retained_orgs = update_all_org_billing_quotas()
        assert data_retained_orgs["events"] == {}
        assert data_retained_orgs["recordings"] == {}
        assert data_retained_orgs["rows_synced"] == {}
        assert quota_limited_orgs["events"] == {}
        assert quota_limited_orgs["recordings"] == {}
        assert quota_limited_orgs["rows_synced"] == {}

        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}events", 0, -1) == []
        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}recordings", 0, -1) == []
        assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}rows_synced", 0, -1) == []

    def test_billing_rate_limit(self) -> None:
        with self.settings(USE_TZ=False), freeze_time("2021-01-25T22:09:14.252Z"):
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
        org_id = str(self.organization.id)

        with freeze_time("2021-01-25T22:09:14.252Z"):
            # Should be data_retained until Jan 28 2021
            quota_limited_orgs, data_retained_orgs = update_all_org_billing_quotas()
            assert data_retained_orgs["events"] == {org_id: 1611792000}
            assert quota_limited_orgs["events"] == {}
            assert quota_limited_orgs["recordings"] == {}
            assert quota_limited_orgs["rows_synced"] == {}

            assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}events", 0, -1) == []
            assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}recordings", 0, -1) == []
            assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}rows_synced", 0, -1) == []

            self.organization.refresh_from_db()
            assert self.organization.usage == {
                "events": {"usage": 99, "limit": 100, "todays_usage": 10, "retained_period_end": 1611792000},
                "recordings": {"usage": 1, "limit": 100, "todays_usage": 0},
                "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 0},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }

        with freeze_time("2021-01-27T22:09:14.252Z"):
            self.organization.usage = {
                "events": {"usage": 109, "limit": 100, "retained_period_end": 1611792000},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 5, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()
            # Fast forward two days and should still be data retained until Jan 28 2021
            quota_limited_orgs, data_retained_orgs = update_all_org_billing_quotas()
            assert data_retained_orgs["events"] == {org_id: 1611792000}
            assert quota_limited_orgs["events"] == {}
            assert quota_limited_orgs["recordings"] == {}
            assert quota_limited_orgs["rows_synced"] == {}

            assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}events", 0, -1) == []
            assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}recordings", 0, -1) == []
            assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}rows_synced", 0, -1) == []

            self.organization.refresh_from_db()
            assert self.organization.usage == {
                "events": {"usage": 109, "limit": 100, "todays_usage": 0, "retained_period_end": 1611792000},
                "recordings": {"usage": 1, "limit": 100, "todays_usage": 0},
                "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 0},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }

        with freeze_time("2021-02-2T22:09:14.252Z"):
            self.organization.usage = {
                "events": {"usage": 109, "limit": 100, "retained_period_end": 1611792000},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 5, "limit": 100},
                "period": ["2021-01-05T00:00:00Z", "2021-02-05T23:59:59Z"],
            }
            self.organization.save()
            # Fast forward eight days and should no longer be data retained, still in same billing period
            quota_limited_orgs, data_retained_orgs = update_all_org_billing_quotas()
            assert data_retained_orgs["events"] == {}
            assert quota_limited_orgs["events"] == {org_id: 1612569599}
            assert quota_limited_orgs["recordings"] == {}
            assert quota_limited_orgs["rows_synced"] == {}

            assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]
            assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}recordings", 0, -1) == []
            assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}rows_synced", 0, -1) == []

            self.organization.refresh_from_db()
            assert self.organization.usage == {
                "events": {"usage": 109, "limit": 100, "todays_usage": 0, "retained_period_end": 1611792000},
                "recordings": {"usage": 1, "limit": 100, "todays_usage": 0},
                "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 0},
                "period": ["2021-01-05T00:00:00Z", "2021-02-05T23:59:59Z"],
            }

        with freeze_time("2021-02-2T22:09:14.252Z"):
            self.organization.usage = {
                "events": {"usage": 109, "limit": 100, "retained_period_end": 1612137600},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 5, "limit": 100},
                "period": ["2021-02-01T00:00:00Z", "2021-02-28T23:59:59Z"],
            }
            self.organization.save()
            # Fast forward two days and should still be data retained but with updated retention end because of new biling period
            quota_limited_orgs, data_retained_orgs = update_all_org_billing_quotas()
            assert data_retained_orgs["events"] == {org_id: 1612483200}
            assert quota_limited_orgs["events"] == {}
            assert quota_limited_orgs["recordings"] == {}
            assert quota_limited_orgs["rows_synced"] == {}

            assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}events", 0, -1) == []
            assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}recordings", 0, -1) == []
            assert self.redis_client.zrange(f"{QUOTA_LIMITER_CACHE_KEY}rows_synced", 0, -1) == []

            self.organization.refresh_from_db()
            assert self.organization.usage == {
                "events": {"usage": 109, "limit": 100, "todays_usage": 0, "retained_period_end": 1612483200},
                "recordings": {"usage": 1, "limit": 100, "todays_usage": 0},
                "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 0},
                "period": ["2021-02-01T00:00:00Z", "2021-02-28T23:59:59Z"],
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

    @freeze_time("2021-01-25T22:09:14.252Z")
    def test_org_quota_limited_until(self):
        self.organization.usage = None
        assert determine_org_quota_limit_or_data_retention(self.organization, QuotaResource.EVENTS) is None

        self.organization.usage = {
            "events": {"usage": 99, "limit": 100},
            "recordings": {"usage": 1, "limit": 100},
            "rows_synced": {"usage": 99, "limit": 100},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }

        assert determine_org_quota_limit_or_data_retention(self.organization, QuotaResource.EVENTS) is None

        self.organization.usage["events"]["usage"] = 120
        assert determine_org_quota_limit_or_data_retention(self.organization, QuotaResource.EVENTS) == {
            "data_retained_until": 1611792000,
            "needs_save": True,
            "quota_limited_until": 1612137599,
        }

        self.organization.usage["events"]["usage"] = 90
        self.organization.usage["events"]["todays_usage"] = 10
        assert determine_org_quota_limit_or_data_retention(self.organization, QuotaResource.EVENTS) == {
            "data_retained_until": 1611792000,
            "needs_save": False,
            "quota_limited_until": 1612137599,
        }

        self.organization.usage["events"]["limit"] = None
        assert determine_org_quota_limit_or_data_retention(self.organization, QuotaResource.EVENTS) is None

        self.organization.usage["recordings"]["usage"] = 1099  # Under limit + buffer
        assert determine_org_quota_limit_or_data_retention(self.organization, QuotaResource.RECORDINGS) is None

        self.organization.usage["recordings"]["usage"] = 1100  # Over limit + buffer
        assert determine_org_quota_limit_or_data_retention(self.organization, QuotaResource.RECORDINGS) == {
            "data_retained_until": 1611792000,
            "needs_save": True,
            "quota_limited_until": 1612137599,
        }

        assert determine_org_quota_limit_or_data_retention(self.organization, QuotaResource.ROWS_SYNCED) is None

        self.organization.usage["rows_synced"]["usage"] = 101
        assert determine_org_quota_limit_or_data_retention(self.organization, QuotaResource.ROWS_SYNCED) == {
            "data_retained_until": 1611792000,
            "needs_save": True,
            "quota_limited_until": 1612137599,
        }

    @freeze_time("2021-01-25T22:09:14.252Z")
    def test_over_quota_but_not_dropped_org(self):
        self.organization.usage = None
        assert determine_org_quota_limit_or_data_retention(self.organization, QuotaResource.EVENTS) is None

        self.organization.usage = {
            "events": {"usage": 100, "limit": 90},
            "recordings": {"usage": 100, "limit": 90},
            "rows_synced": {"usage": 100, "limit": 90},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.never_drop_data = True

        assert determine_org_quota_limit_or_data_retention(self.organization, QuotaResource.EVENTS) is None
        assert determine_org_quota_limit_or_data_retention(self.organization, QuotaResource.RECORDINGS) is None
        assert determine_org_quota_limit_or_data_retention(self.organization, QuotaResource.ROWS_SYNCED) is None

        # reset for subsequent tests
        self.organization.never_drop_data = False

    def test_sync_org_quota_limits(self):
        with freeze_time("2021-01-01T12:59:59Z"):
            other_team = create_team(organization=self.organization)

            now = timezone.now().timestamp()

            replace_limited_team_tokens(QuotaResource.EVENTS, {"1234": now + 10000}, QUOTA_LIMITER_CACHE_KEY)
            replace_limited_team_tokens(QuotaResource.ROWS_SYNCED, {"1337": now + 10000}, QUOTA_LIMITER_CACHE_KEY)
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
            # Org will be data retained.
            assert self.organization.usage == {
                "events": {"usage": 120, "limit": 100, "retained_period_end": 1609718400},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"limit": 100, "retained_period_end": 1609718400, "usage": 120},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            assert sorted(
                list_limited_team_attributes(QuotaResource.EVENTS, QUOTA_OVERAGE_RETENTION_CACHE_KEY)
            ) == sorted([self.team.api_token, other_team.api_token])
            assert sorted(list_limited_team_attributes(QuotaResource.EVENTS)) == sorted(["1234"])

            # rows_synced uses teams, not tokens
            assert sorted(
                list_limited_team_attributes(QuotaResource.ROWS_SYNCED, QUOTA_OVERAGE_RETENTION_CACHE_KEY)
            ) == sorted([str(self.team.pk), str(other_team.pk)])
            assert sorted(list_limited_team_attributes(QuotaResource.ROWS_SYNCED)) == sorted(["1337"])

            self.organization.usage["events"]["usage"] = 80
            self.organization.usage["rows_synced"]["usage"] = 36
            sync_org_quota_limits(self.organization)
            assert self.organization.usage == {
                "events": {"usage": 80, "limit": 100},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"limit": 100, "usage": 36},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            assert sorted(list_limited_team_attributes(QuotaResource.EVENTS)) == sorted(["1234"])
            assert sorted(
                list_limited_team_attributes(QuotaResource.EVENTS, QUOTA_OVERAGE_RETENTION_CACHE_KEY)
            ) == sorted([])
            assert sorted(list_limited_team_attributes(QuotaResource.ROWS_SYNCED)) == sorted(["1337"])
            assert sorted(
                list_limited_team_attributes(QuotaResource.ROWS_SYNCED, QUOTA_OVERAGE_RETENTION_CACHE_KEY)
            ) == sorted([])
