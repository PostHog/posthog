import time
from unittest.mock import patch
from uuid import uuid4

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.utils.timezone import now
from freezegun import freeze_time

from ee.billing.quota_limiting import (
    QUOTA_LIMIT_DATA_RETENTION_FLAG,
    QuotaLimitingCaches,
    QuotaResource,
    add_limited_team_tokens,
    get_team_attribute_by_quota_resource,
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
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.redis_client = get_client()
        self.redis_client.delete(f"@posthog/quota-limits/events")
        self.redis_client.delete(f"@posthog/quota-limits/recordings")
        self.redis_client.delete(f"@posthog/quota-limits/rows_synced")
        self.redis_client.delete(f"@posthog/quota-limiting-suspended/events")
        self.redis_client.delete(f"@posthog/quota-limiting-suspended/recordings")
        self.redis_client.delete(f"@posthog/quota-limiting-suspended/rows_synced")

    @patch("posthoganalytics.capture")
    @patch("posthoganalytics.feature_enabled", return_value=True)
    @freeze_time("2021-01-25T23:59:59Z")
    def test_quota_limiting_feature_flag_enabled(self, patch_feature_enabled, patch_capture) -> None:
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
            for _ in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=1),
                    team=self.team,
                )

        org_id = str(self.organization.id)
        time.sleep(1)

        quota_limited_orgs, quota_limiting_suspended_orgs = update_all_org_billing_quotas()
        patch_feature_enabled.assert_called_with(
            QUOTA_LIMIT_DATA_RETENTION_FLAG,
            self.organization.id,
            groups={"organization": org_id},
            group_properties={"organization": {"id": str(org_id)}},
        )
        patch_capture.assert_called_once_with(
            str(org_id),
            "quota limiting suspended",
            properties={"current_usage": 109},
            groups={"instance": "http://localhost:8000", "organization": org_id},
        )
        # Feature flag is enabled so they won't be limited.
        assert quota_limited_orgs["events"] == {}
        assert quota_limited_orgs["recordings"] == {}
        assert quota_limited_orgs["rows_synced"] == {}
        assert quota_limiting_suspended_orgs["events"] == {}
        assert quota_limiting_suspended_orgs["recordings"] == {}
        assert quota_limiting_suspended_orgs["rows_synced"] == {}
        assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []

        patch_capture.reset_mock()
        # Add this org to the redis cache.
        team_tokens = get_team_attribute_by_quota_resource(self.organization)
        add_limited_team_tokens(
            QuotaResource.EVENTS,
            {x: 1612137599 for x in team_tokens},
            QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
        )
        quota_limited_orgs, quota_limiting_suspended_orgs = update_all_org_billing_quotas()
        patch_feature_enabled.assert_called_with(
            QUOTA_LIMIT_DATA_RETENTION_FLAG,
            self.organization.id,
            groups={"organization": org_id},
            group_properties={"organization": {"id": org_id}},
        )
        patch_capture.assert_not_called()

        # Feature flag is on but we only suspend limiting for orgs that were not previously limited. This org should still be in the set.
        # NOTE on the asserted dict: org_id is a variable (see above), not a string key, and the value is the timestamp at which
        # quota_limiting should end or quota_limiting_suspension should end.
        assert quota_limited_orgs["events"] == {org_id: 1612137599}
        assert quota_limited_orgs["recordings"] == {}
        assert quota_limited_orgs["rows_synced"] == {}
        assert quota_limiting_suspended_orgs["events"] == {}
        assert quota_limiting_suspended_orgs["recordings"] == {}
        assert quota_limiting_suspended_orgs["rows_synced"] == {}
        assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == [self.team.api_token.encode("UTF-8")]
        assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []

    @patch("posthoganalytics.capture")
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_quota_limit_feature_flag_not_on(self, patch_feature_enabled, patch_capture) -> None:
        # Confirm that we don't send an event if they weren't going to be limited.
        self.organization.usage = {
            "events": {"usage": 99, "limit": 100, "todays_usage": 0},
            "recordings": {"usage": 1, "limit": 100, "todays_usage": 0},
            "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 0},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.customer_trust_scores = {"events": 0, "recordings": 0, "rows_synced": 0}
        self.organization.save()

        time.sleep(1)
        with self.assertNumQueries(3):
            quota_limited_orgs, quota_limiting_suspended_orgs = update_all_org_billing_quotas()
        # Shouldn't be called due to lazy evaluation of the conditional
        patch_feature_enabled.assert_not_called()
        patch_capture.assert_not_called()
        assert quota_limited_orgs["events"] == {}
        assert quota_limited_orgs["recordings"] == {}
        assert quota_limited_orgs["rows_synced"] == {}
        assert quota_limiting_suspended_orgs["events"] == {}
        assert quota_limiting_suspended_orgs["recordings"] == {}
        assert quota_limiting_suspended_orgs["rows_synced"] == {}

        assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []

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

        quota_limited_orgs, quota_limiting_suspended_orgs = update_all_org_billing_quotas()
        assert quota_limited_orgs["events"] == {}
        assert quota_limited_orgs["recordings"] == {}
        assert quota_limited_orgs["rows_synced"] == {}
        assert quota_limiting_suspended_orgs["events"] == {}
        assert quota_limiting_suspended_orgs["recordings"] == {}
        assert quota_limiting_suspended_orgs["rows_synced"] == {}

        assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []

    @patch("posthoganalytics.capture")
    def test_billing_rate_limit(self, patch_capture) -> None:
        with self.settings(USE_TZ=False), freeze_time("2021-01-25T00:00:00Z"):
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
                    timestamp=now(),
                    team=self.team,
                )
            time.sleep(1)
            quota_limited_orgs, quota_limiting_suspended_orgs = update_all_org_billing_quotas()
            # Will be immediately rate limited as trust score was unset.
            org_id = str(self.organization.id)
            assert quota_limited_orgs["events"] == {org_id: 1612137599}
            assert quota_limited_orgs["recordings"] == {}
            assert quota_limited_orgs["rows_synced"] == {}
            assert quota_limiting_suspended_orgs["events"] == {}
            assert quota_limiting_suspended_orgs["recordings"] == {}
            assert quota_limiting_suspended_orgs["rows_synced"] == {}

            patch_capture.assert_called_once_with(
                org_id,
                "organization quota limits changed",
                properties={
                    "quota_limited_events": 1612137599,
                    "quota_limited_recordings": 1612137599,
                    "quota_limited_rows_synced": None,
                },
                groups={"instance": "http://localhost:8000", "organization": org_id},
            )

            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]
            assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []

            self.organization.refresh_from_db()
            assert self.organization.usage == {
                "events": {"usage": 99, "limit": 100, "todays_usage": 10},
                "recordings": {"usage": 1, "limit": 100, "todays_usage": 0},
                "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 0},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }

            # # Increase the trust score. They are already being limited, so we will not suspend their limiting.
            self.organization.customer_trust_scores = {"events": 7, "recordings": 0, "rows_synced": 0}
            self.organization.save()
            quota_limited_orgs, quota_limiting_suspended_orgs = update_all_org_billing_quotas()

            assert quota_limited_orgs["events"] == {org_id: 1612137599}
            assert quota_limited_orgs["recordings"] == {}
            assert quota_limited_orgs["rows_synced"] == {}
            assert quota_limiting_suspended_orgs["events"] == {}
            assert quota_limiting_suspended_orgs["recordings"] == {}
            assert quota_limiting_suspended_orgs["rows_synced"] == {}
            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]
            assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []

            # Reset the event limiting set so their limiting will be suspended for 1 day.
            self.redis_client.delete(f"@posthog/quota-limits/events")
            quota_limited_orgs, quota_limiting_suspended_orgs = update_all_org_billing_quotas()
            assert quota_limited_orgs["events"] == {}
            assert quota_limited_orgs["recordings"] == {}
            assert quota_limited_orgs["rows_synced"] == {}
            assert quota_limiting_suspended_orgs["events"] == {org_id: 1611705600}
            assert quota_limiting_suspended_orgs["recordings"] == {}
            assert quota_limiting_suspended_orgs["rows_synced"] == {}
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]

            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []

        # Check that limiting still suspended 23 hrs later
        with freeze_time("2021-01-25T23:00:00Z"):
            quota_limited_orgs, quota_limiting_suspended_orgs = update_all_org_billing_quotas()
            assert quota_limited_orgs["events"] == {}
            assert quota_limited_orgs["recordings"] == {}
            assert quota_limited_orgs["rows_synced"] == {}
            assert quota_limiting_suspended_orgs["events"] == {org_id: 1611705600}
            assert quota_limiting_suspended_orgs["recordings"] == {}
            assert quota_limiting_suspended_orgs["rows_synced"] == {}
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]

            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []
            self.organization.refresh_from_db()
            assert self.organization.usage == {
                "events": {
                    "usage": 99,
                    "limit": 100,
                    "todays_usage": 10,
                    "quota_limiting_suspended_until": 1611705600,
                },
                "recordings": {"usage": 1, "limit": 100, "todays_usage": 0},
                "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 0},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }

        # Check that org is being limited after suspension expired
        with freeze_time("2021-01-27T03:00:00Z"):
            self.organization.usage = {
                "events": {"usage": 109, "limit": 100, "quota_limiting_suspended_until": 1611705600},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 5, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()
            quota_limited_orgs, quota_limiting_suspended_orgs = update_all_org_billing_quotas()
            assert quota_limited_orgs["events"] == {org_id: 1612137599}
            assert quota_limited_orgs["recordings"] == {}
            assert quota_limited_orgs["rows_synced"] == {}
            assert quota_limiting_suspended_orgs["events"] == {}
            assert quota_limiting_suspended_orgs["recordings"] == {}
            assert quota_limiting_suspended_orgs["rows_synced"] == {}
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == []

            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]
            assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []

        # Increase trust score. Their quota limiting suspension expiration should not update.
        with freeze_time("2021-01-25T00:00:00Z"):
            assert self.redis_client.delete(f"@posthog/quota-limits/events")

            self.organization.customer_trust_scores = {"events": 10, "recordings": 0, "rows_synced": 0}
            self.organization.usage = {
                "events": {"usage": 109, "limit": 100, "quota_limiting_suspended_until": 1611705600},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 5, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()
            quota_limited_orgs, quota_limiting_suspended_orgs = update_all_org_billing_quotas()
            assert quota_limited_orgs["events"] == {}
            assert quota_limited_orgs["recordings"] == {}
            assert quota_limited_orgs["rows_synced"] == {}
            assert quota_limiting_suspended_orgs["events"] == {org_id: 1611705600}
            assert quota_limiting_suspended_orgs["recordings"] == {}
            assert quota_limiting_suspended_orgs["rows_synced"] == {}
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]

            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []

            # Reset, quota limiting should be suspended for 3 days.
            self.organization.customer_trust_scores = {"events": 10, "recordings": 0, "rows_synced": 0}
            self.organization.usage = {
                "events": {"usage": 109, "limit": 100},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 5, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()
            quota_limited_orgs, quota_limiting_suspended_orgs = update_all_org_billing_quotas()
            assert quota_limited_orgs["events"] == {}
            assert quota_limited_orgs["recordings"] == {}
            assert quota_limited_orgs["rows_synced"] == {}
            assert quota_limiting_suspended_orgs["events"] == {org_id: 1611878400}
            assert quota_limiting_suspended_orgs["recordings"] == {}
            assert quota_limiting_suspended_orgs["rows_synced"] == {}
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]

            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []

            # Decrease the trust score to 0. Quota limiting should immediately take effect.
            self.organization.customer_trust_scores = {"events": 0, "recordings": 0, "rows_synced": 0}
            self.organization.usage = {
                "events": {"usage": 109, "limit": 100, "quota_limiting_suspended_until": 1611705600},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 5, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()
            quota_limited_orgs, quota_limiting_suspended_orgs = update_all_org_billing_quotas()
            assert quota_limited_orgs["events"] == {org_id: 1612137599}
            assert quota_limited_orgs["recordings"] == {}
            assert quota_limited_orgs["rows_synced"] == {}
            assert quota_limiting_suspended_orgs["events"] == {}
            assert quota_limiting_suspended_orgs["recordings"] == {}
            assert quota_limiting_suspended_orgs["rows_synced"] == {}
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == []

            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]
            assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []

        with freeze_time("2021-01-28T00:00:00Z"):
            self.redis_client.delete(f"@posthog/quota-limits/events")

            # Quota limiting suspension date set in previous billing period, update to new suspension expiration
            self.organization.customer_trust_scores = {"events": 10, "recordings": 0, "rows_synced": 0}
            self.organization.usage = {
                "events": {"usage": 109, "limit": 100, "quota_limiting_suspended_until": 1611705600},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 5, "limit": 100},
                "period": ["2021-01-27T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()

            quota_limited_orgs, quota_limiting_suspended_orgs = update_all_org_billing_quotas()
            assert quota_limited_orgs["events"] == {}
            assert quota_limited_orgs["recordings"] == {}
            assert quota_limited_orgs["rows_synced"] == {}
            assert quota_limiting_suspended_orgs["events"] == {org_id: 1612137600}
            assert quota_limiting_suspended_orgs["recordings"] == {}
            assert quota_limiting_suspended_orgs["rows_synced"] == {}
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]

            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []

    def test_set_org_usage_summary_updates_correctly(self):
        self.organization.usage = {
            "events": {"usage": 99, "limit": 100},
            "recordings": {"usage": 1, "limit": 100},
            "rows_synced": {"usage": 5, "limit": 100},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.save()

        new_usage = {
            "events": {"usage": 100, "limit": 100},
            "recordings": {"usage": 2, "limit": 100},
            "rows_synced": {"usage": 6, "limit": 100},
            "period": [
                "2021-01-01T00:00:00Z",
                "2021-01-31T23:59:59Z",
            ],
        }

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

        new_usage = {
            "events": {"usage": 99, "limit": 100},
            "recordings": {"usage": 1, "limit": 100},
            "rows_synced": {"usage": 5, "limit": 100},
            "period": [
                "2021-01-01T00:00:00Z",
                "2021-01-31T23:59:59Z",
            ],
        }

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
        self.organization.customer_trust_scores = {"events": 0, "recordings": 0, "rows_synced": 0}
        previously_quota_limited_team_tokens_events = list_limited_team_attributes(
            QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_recordings = list_limited_team_attributes(
            QuotaResource.RECORDINGS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_rows_synced = list_limited_team_attributes(
            QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
            )
            is None
        )

        self.organization.usage = {
            "events": {"usage": 99, "limit": 100},
            "recordings": {"usage": 1, "limit": 100},
            "rows_synced": {"usage": 99, "limit": 100},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }

        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
            )
            is None
        )

        self.organization.usage["events"]["usage"] = 120
        assert org_quota_limited_until(
            self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
        ) == {
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }

        self.organization.usage["events"]["usage"] = 90
        self.organization.usage["events"]["todays_usage"] = 10
        assert org_quota_limited_until(
            self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
        ) == {
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }

        self.organization.usage["events"]["limit"] = None
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
            )
            is None
        )

        self.organization.usage["recordings"]["usage"] = 1099  # Under limit + buffer
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.RECORDINGS, previously_quota_limited_team_tokens_recordings
            )
            is None
        )

        self.organization.usage["recordings"]["usage"] = 1100  # Over limit + buffer
        assert org_quota_limited_until(
            self.organization, QuotaResource.RECORDINGS, previously_quota_limited_team_tokens_recordings
        ) == {
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }

        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.ROWS_SYNCED, previously_quota_limited_team_tokens_rows_synced
            )
            is None
        )

        self.organization.usage["rows_synced"]["usage"] = 101
        assert org_quota_limited_until(
            self.organization, QuotaResource.ROWS_SYNCED, previously_quota_limited_team_tokens_rows_synced
        ) == {
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }

        with freeze_time("2021-01-25T00:00:00Z"):
            self.organization.customer_trust_scores = {"events": 7, "recordings": 3, "rows_synced": 10}
            self.organization.usage["rows_synced"]["usage"] = 101
            self.organization.usage["events"]["limit"] = 100
            self.organization.usage["events"]["usage"] = 101
            self.organization.usage["recordings"]["usage"] = 1100
            assert org_quota_limited_until(
                self.organization, QuotaResource.ROWS_SYNCED, previously_quota_limited_team_tokens_rows_synced
            ) == {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": 1611878400,
            }
            assert org_quota_limited_until(
                self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
            ) == {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": 1611705600,
            }
            assert org_quota_limited_until(
                self.organization, QuotaResource.RECORDINGS, previously_quota_limited_team_tokens_recordings
            ) == {
                "quota_limited_until": 1612137599,
                "quota_limiting_suspended_until": None,
            }

        self.organization.customer_trust_scores = {"events": 7, "rows_synced": 10}
        self.organization.save()
        assert org_quota_limited_until(
            self.organization, QuotaResource.RECORDINGS, previously_quota_limited_team_tokens_rows_synced
        ) == {
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }
        self.organization.refresh_from_db()
        assert self.organization.customer_trust_scores == {"events": 7, "recordings": 0, "rows_synced": 10}

    def test_over_quota_but_not_dropped_org(self):
        self.organization.usage = None
        previously_quota_limited_team_tokens_events = list_limited_team_attributes(
            QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_recordings = list_limited_team_attributes(
            QuotaResource.RECORDINGS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_rows_synced = list_limited_team_attributes(
            QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
            )
            is None
        )

        self.organization.usage = {
            "events": {"usage": 100, "limit": 90},
            "recordings": {"usage": 100, "limit": 90},
            "rows_synced": {"usage": 100, "limit": 90},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.never_drop_data = True

        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
            )
            is None
        )
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.RECORDINGS, previously_quota_limited_team_tokens_recordings
            )
            is None
        )
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.ROWS_SYNCED, previously_quota_limited_team_tokens_rows_synced
            )
            is None
        )

        # reset for subsequent tests
        self.organization.never_drop_data = False

    def test_sync_org_quota_limits(self):
        with freeze_time("2021-01-01T12:59:59Z"):
            other_team = create_team(organization=self.organization)

            now = timezone.now().timestamp()

            replace_limited_team_tokens(
                QuotaResource.EVENTS, {"1234": now + 10000}, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )
            replace_limited_team_tokens(
                QuotaResource.ROWS_SYNCED, {"1337": now + 10000}, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )
            self.organization.usage = {
                "events": {"usage": 99, "limit": 100},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 35, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }

            sync_org_quota_limits(self.organization)
            assert list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY) == [
                "1234"
            ]
            assert list_limited_team_attributes(
                QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            ) == ["1337"]

            self.organization.usage["events"]["usage"] = 120
            self.organization.usage["rows_synced"]["usage"] = 120
            sync_org_quota_limits(self.organization)
            assert sorted(
                list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1234", self.team.api_token, other_team.api_token])

            # rows_synced uses teams, not tokens
            assert sorted(
                list_limited_team_attributes(QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1337", str(self.team.api_token), str(other_team.api_token)])

            self.organization.usage["events"]["usage"] = 80
            self.organization.usage["rows_synced"]["usage"] = 36
            sync_org_quota_limits(self.organization)
            assert sorted(
                list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1234"])
            assert sorted(
                list_limited_team_attributes(QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1337"])

            self.organization.customer_trust_scores = {"events": 10, "recordings": 0, "rows_synced": 7}
            self.organization.save()

            self.organization.usage["events"]["usage"] = 120
            self.organization.usage["rows_synced"]["usage"] = 120
            sync_org_quota_limits(self.organization)
            assert sorted(
                list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1234"])
            assert sorted(
                list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY)
            ) == sorted([self.team.api_token, other_team.api_token])

            # rows_synced uses teams, not tokens
            assert sorted(
                list_limited_team_attributes(QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1337"])
            assert sorted(
                list_limited_team_attributes(
                    QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY
                )
            ) == sorted([str(self.team.api_token), str(other_team.api_token)])

            self.organization.usage["events"]["usage"] = 80
            self.organization.usage["rows_synced"]["usage"] = 36
            sync_org_quota_limits(self.organization)
            assert sorted(
                list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1234"])
            assert sorted(
                list_limited_team_attributes(QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1337"])
