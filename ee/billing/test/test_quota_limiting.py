import time
from typing import Any, cast
from uuid import uuid4

from freezegun import freeze_time
from posthog.test.base import BaseTest, FuzzyInt, _create_event
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized

from posthog.api.test.test_team import create_team
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.redis import get_client

from ee.billing.quota_limiting import (
    QUOTA_LIMIT_DATA_RETENTION_FLAG,
    OrganizationUsageInfo,
    QuotaLimitingCaches,
    QuotaResource,
    UsageCounters,
    _identify_refresh_candidates,
    _patch_todays_usage,
    add_limited_team_tokens,
    get_team_attribute_by_quota_resource,
    list_limited_team_attributes,
    org_quota_limited_until,
    replace_limited_team_tokens,
    set_org_usage_summary,
    update_all_orgs_billing_quotas,
    update_org_billing_quotas,
    update_organization_usage_fields,
)
from ee.clickhouse.materialized_columns.columns import materialize


def zero_trust_scores():
    return {resource.value: 0 for resource in QuotaResource}


@override_settings(CLOUD_DEPLOYMENT="US")  # As PostHog Cloud
class TestQuotaLimiting(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.redis_client = get_client()
        self.redis_client.delete(f"@posthog/quota-limits/events")
        self.redis_client.delete(f"@posthog/quota-limits/exceptions")
        self.redis_client.delete(f"@posthog/quota-limits/recordings")
        self.redis_client.delete(f"@posthog/quota-limits/rows_synced")
        self.redis_client.delete(f"@posthog/quota-limits/api_queries_read_bytes")
        self.redis_client.delete(f"@posthog/quota-limits/survey_responses")
        self.redis_client.delete(f"@posthog/quota-limits/rows_exported")
        self.redis_client.delete(f"@posthog/quota-limits/llm_events")
        self.redis_client.delete(f"@posthog/quota-limits/cdp_trigger_events")
        self.redis_client.delete(f"@posthog/quota-limits/ai_credits")
        self.redis_client.delete(f"@posthog/quota-limiting-suspended/events")
        self.redis_client.delete(f"@posthog/quota-limiting-suspended/exceptions")
        self.redis_client.delete(f"@posthog/quota-limiting-suspended/recordings")
        self.redis_client.delete(f"@posthog/quota-limiting-suspended/rows_synced")
        self.redis_client.delete(f"@posthog/quota-limiting-suspended/api_queries_read_bytes")
        self.redis_client.delete(f"@posthog/quota-limiting-suspended/survey_responses")
        self.redis_client.delete(f"@posthog/quota-limiting-suspended/rows_exported")
        self.redis_client.delete(f"@posthog/quota-limiting-suspended/llm_events")
        self.redis_client.delete(f"@posthog/quota-limiting-suspended/cdp_trigger_events")
        self.redis_client.delete(f"@posthog/quota-limiting-suspended/ai_credits")
        materialize("events", "$exception_values")

    @patch("posthoganalytics.capture")
    @patch("posthoganalytics.feature_enabled", return_value=True)
    @freeze_time("2021-01-25T23:59:59Z")
    def test_quota_limiting_feature_flag_enabled(self, patch_feature_enabled, patch_capture) -> None:
        with self.settings(USE_TZ=False):
            self.organization.usage = {
                "events": {"usage": 99, "limit": 100},
                "exceptions": {"usage": 10, "limit": 100},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 5, "limit": 100},
                "feature_flag_requests": {"usage": 5, "limit": 100},
                "api_queries_read_bytes": {"usage": 10, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
                "survey_responses": {"usage": 10, "limit": 100},
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

        quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
        # feature_enabled will be called for AI billing check and then for data retention flag
        patch_feature_enabled.assert_any_call(
            QUOTA_LIMIT_DATA_RETENTION_FLAG,
            str(self.organization.id),
            groups={"organization": org_id},
            group_properties={"organization": {"id": str(org_id)}},
        )
        # Check out many times it was called
        assert patch_capture.call_count == 1  # 1 org event from org_quota_limited_until
        # Find the org action call
        org_action_call = next(
            call for call in patch_capture.call_args_list if call.kwargs.get("event") == "org_quota_limited_until"
        )
        assert org_action_call.kwargs.get("properties") == {
            "event": "ignored",
            "current_usage": 109,
            "resource": "events",
            "feature_flag": QUOTA_LIMIT_DATA_RETENTION_FLAG,
        }
        assert org_action_call.kwargs.get("groups") == {
            "instance": "http://localhost:8010",
            "organization": org_id,
        }
        # Feature flag is enabled so they won't be limited.
        assert quota_limited_orgs["events"] == {}
        assert quota_limited_orgs["exceptions"] == {}
        assert quota_limited_orgs["recordings"] == {}
        assert quota_limited_orgs["rows_synced"] == {}
        assert quota_limited_orgs["feature_flag_requests"] == {}
        assert quota_limited_orgs["api_queries_read_bytes"] == {}
        assert quota_limited_orgs["survey_responses"] == {}
        assert quota_limited_orgs["rows_exported"] == {}
        assert quota_limiting_suspended_orgs["events"] == {}
        assert quota_limiting_suspended_orgs["exceptions"] == {}
        assert quota_limiting_suspended_orgs["recordings"] == {}
        assert quota_limiting_suspended_orgs["rows_synced"] == {}
        assert quota_limiting_suspended_orgs["feature_flag_requests"] == {}
        assert quota_limiting_suspended_orgs["api_queries_read_bytes"] == {}
        assert quota_limiting_suspended_orgs["survey_responses"] == {}
        assert quota_limiting_suspended_orgs["rows_exported"] == {}
        assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/exceptions", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/feature_flag_requests", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/api_queries_read_bytes", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/survey_responses", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/rows_exported", 0, -1) == []

        patch_capture.reset_mock()
        # Add this org to the redis cache.
        team_tokens = get_team_attribute_by_quota_resource(self.organization)
        add_limited_team_tokens(
            QuotaResource.EVENTS,
            dict.fromkeys(team_tokens, 1612137599),
            QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
        )
        quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
        # Check out many times it was called
        assert patch_capture.call_count == 1  # 1 org event from org_quota_limited_until
        # Find the org action call
        org_action_call = next(
            call for call in patch_capture.call_args_list if call.kwargs.get("event") == "org_quota_limited_until"
        )
        assert org_action_call.kwargs.get("properties") == {
            "event": "already limited",
            "current_usage": 109,
            "resource": "events",
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }
        assert org_action_call.kwargs.get("groups") == {
            "instance": "http://localhost:8010",
            "organization": org_id,
        }

        # Feature flag is on but we only suspend limiting for orgs that were not previously limited. This org should still be in the set.
        # NOTE on the asserted dict: org_id is a variable (see above), not a string key, and the value is the timestamp at which
        # quota_limiting should end or quota_limiting_suspension should end.
        assert quota_limited_orgs["events"] == {org_id: 1612137599}
        assert quota_limited_orgs["exceptions"] == {}
        assert quota_limited_orgs["recordings"] == {}
        assert quota_limited_orgs["rows_synced"] == {}
        assert quota_limited_orgs["feature_flag_requests"] == {}
        assert quota_limited_orgs["api_queries_read_bytes"] == {}
        assert quota_limited_orgs["survey_responses"] == {}
        assert quota_limited_orgs["rows_exported"] == {}
        assert quota_limiting_suspended_orgs["events"] == {}
        assert quota_limiting_suspended_orgs["exceptions"] == {}
        assert quota_limiting_suspended_orgs["recordings"] == {}
        assert quota_limiting_suspended_orgs["rows_synced"] == {}
        assert quota_limiting_suspended_orgs["feature_flag_requests"] == {}
        assert quota_limiting_suspended_orgs["api_queries_read_bytes"] == {}
        assert quota_limiting_suspended_orgs["survey_responses"] == {}
        assert quota_limiting_suspended_orgs["rows_exported"] == {}
        assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == [self.team.api_token.encode("UTF-8")]
        assert self.redis_client.zrange(f"@posthog/quota-limits/exceptions", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/feature_flag_requests", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/api_queries_read_bytes", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/survey_responses", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/rows_exported", 0, -1) == []

    @patch("posthoganalytics.capture")
    def test_quota_limit_feature_flag_not_on(self, patch_capture) -> None:
        # Confirm that we don't send an event if they weren't going to be limited.
        self.organization.usage = {
            "events": {"usage": 99, "limit": 100, "todays_usage": 0},
            "exceptions": {"usage": 10, "limit": 100, "todays_usage": 0},
            "recordings": {"usage": 1, "limit": 100, "todays_usage": 0},
            "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 0},
            "feature_flag_requests": {"usage": 5, "limit": 100, "todays_usage": 0},
            "api_queries_read_bytes": {"usage": 1000, "limit": 1000000, "todays_usage": 0},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            "survey_responses": {"usage": 10, "limit": 100, "todays_usage": 0},
        }
        self.organization.customer_trust_scores = zero_trust_scores()
        self.organization.save()

        time.sleep(1)
        with self.assertNumQueries(FuzzyInt(3, 6)):
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
        assert patch_capture.call_count == 0  # No events should be captured since org won't be limited
        assert quota_limited_orgs["events"] == {}
        assert quota_limited_orgs["exceptions"] == {}
        assert quota_limited_orgs["recordings"] == {}
        assert quota_limited_orgs["rows_synced"] == {}
        assert quota_limited_orgs["feature_flag_requests"] == {}
        assert quota_limited_orgs["api_queries_read_bytes"] == {}
        assert quota_limited_orgs["survey_responses"] == {}
        assert quota_limited_orgs["rows_exported"] == {}
        assert quota_limiting_suspended_orgs["events"] == {}
        assert quota_limiting_suspended_orgs["exceptions"] == {}
        assert quota_limiting_suspended_orgs["recordings"] == {}
        assert quota_limiting_suspended_orgs["rows_synced"] == {}
        assert quota_limiting_suspended_orgs["feature_flag_requests"] == {}
        assert quota_limiting_suspended_orgs["api_queries_read_bytes"] == {}
        assert quota_limiting_suspended_orgs["survey_responses"] == {}
        assert quota_limiting_suspended_orgs["rows_exported"] == {}

        assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/exceptions", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/feature_flag_requests", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/api_queries_read_bytes", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/survey_responses", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/rows_exported", 0, -1) == []

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

        quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
        assert quota_limited_orgs["events"] == {}
        assert quota_limited_orgs["exceptions"] == {}
        assert quota_limited_orgs["recordings"] == {}
        assert quota_limited_orgs["rows_synced"] == {}
        assert quota_limited_orgs["feature_flag_requests"] == {}
        assert quota_limited_orgs["survey_responses"] == {}
        assert quota_limiting_suspended_orgs["events"] == {}
        assert quota_limiting_suspended_orgs["exceptions"] == {}
        assert quota_limiting_suspended_orgs["recordings"] == {}
        assert quota_limiting_suspended_orgs["rows_synced"] == {}
        assert quota_limiting_suspended_orgs["feature_flag_requests"] == {}
        assert quota_limiting_suspended_orgs["survey_responses"] == {}

        assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/exceptions", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/recordings", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/rows_synced", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/feature_flag_requests", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/api_queries_read_bytes", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/survey_responses", 0, -1) == []
        assert self.redis_client.zrange(f"@posthog/quota-limits/rows_exported", 0, -1) == []

    @patch("posthoganalytics.capture")
    def test_billing_rate_limit(self, patch_capture) -> None:
        def create_usage_summary(**kwargs) -> dict[str, Any]:
            data: dict[str, Any] = {
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            for resource in QuotaResource:
                data[resource.value] = {"limit": 100, "usage": 10, "todays_usage": 0}
            data.update(kwargs)
            return data

        def assert_other_resources_not_limited(quota_limited_orgs, quota_limiting_suspended_orgs):
            for resource in QuotaResource:
                if resource != QuotaResource.EVENTS:
                    assert quota_limited_orgs[resource.value] == {}
                    assert quota_limiting_suspended_orgs[resource.value] == {}
                    assert self.redis_client.zrange(f"@posthog/quota-limits/{resource.value}", 0, -1) == []
                    assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/{resource.value}", 0, -1) == []

        with self.settings(USE_TZ=False), freeze_time("2021-01-25T00:00:00Z"):
            self.organization.usage = create_usage_summary(
                events={"usage": 99, "limit": 100},
            )
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
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            # Will be immediately rate limited as trust score was unset.
            org_id = str(self.organization.id)
            assert quota_limited_orgs["events"] == {org_id: 1612137599}
            assert quota_limiting_suspended_orgs["events"] == {}
            assert_other_resources_not_limited(quota_limited_orgs, quota_limiting_suspended_orgs)

            # Check out many times it was called
            assert (
                patch_capture.call_count == 2
            )  # 1 org_quota_limited_until event + 1 organization quota limits changed event
            # Find the org action call
            org_action_call = next(
                call
                for call in patch_capture.call_args_list
                if call.kwargs.get("event") == "organization quota limits changed"
            )
            assert org_action_call.kwargs.get("properties") == {
                "quota_limited_events": 1612137599,
                "quota_limited_exceptions": None,
                "quota_limited_recordings": None,
                "quota_limited_api_queries": None,
                "quota_limited_rows_synced": None,
                "quota_limited_feature_flags": None,
                "quota_limited_survey_responses": None,
                "quota_limited_llm_events": None,
                "quota_limited_cdp_trigger_events": None,
                "quota_limited_rows_exported": None,
            }
            assert org_action_call.kwargs.get("groups") == {
                "instance": "http://localhost:8010",
                "organization": org_id,
            }

            for resource in QuotaResource:
                if resource == QuotaResource.EVENTS:
                    assert self.redis_client.zrange(f"@posthog/quota-limits/{resource.value}", 0, -1) == [
                        self.team.api_token.encode("UTF-8")
                    ]
                else:
                    assert self.redis_client.zrange(f"@posthog/quota-limits/{resource.value}", 0, -1) == []

            self.organization.refresh_from_db()
            assert self.organization.usage == create_usage_summary(
                events={"usage": 99, "limit": 100, "todays_usage": 10, "quota_limited_until": 1612137599}
            )

            # # Increase the trust score. They are already being limited, so we will not suspend their limiting.
            self.organization.customer_trust_scores = {
                "events": 7,
                "exceptions": 0,
                "recordings": 0,
                "rows_synced": 0,
                "feature_flag_requests": 0,
                QuotaResource.API_QUERIES.value: 0,
                "survey_responses": 0,
                "rows_exported": 0,
            }
            self.organization.save()
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()

            assert quota_limited_orgs["events"] == {org_id: 1612137599}
            assert quota_limiting_suspended_orgs["events"] == {}
            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]
            assert_other_resources_not_limited(quota_limited_orgs, quota_limiting_suspended_orgs)

            # Reset the event limiting set so their limiting will be suspended for 1 day.
            self.redis_client.delete(f"@posthog/quota-limits/events")
            self.organization.usage = create_usage_summary(
                events={"usage": 99, "limit": 100, "todays_usage": 0},
            )
            self.organization.save()
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert quota_limited_orgs["events"] == {}
            assert quota_limiting_suspended_orgs["events"] == {org_id: 1611705600}
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]
            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
            assert_other_resources_not_limited(quota_limited_orgs, quota_limiting_suspended_orgs)

        # Check that limiting still suspended 23 hrs later
        with freeze_time("2021-01-25T23:00:00Z"):
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()

            assert quota_limited_orgs["events"] == {}
            assert quota_limiting_suspended_orgs["events"] == {org_id: 1611705600}
            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]
            assert_other_resources_not_limited(quota_limited_orgs, quota_limiting_suspended_orgs)

            self.organization.refresh_from_db()
            assert self.organization.usage == create_usage_summary(
                events={"usage": 99, "limit": 100, "todays_usage": 10, "quota_limiting_suspended_until": 1611705600}
            )

        # Check that org is being limited after suspension expired
        with freeze_time("2021-01-27T03:00:00Z"):
            self.organization.usage = create_usage_summary(
                events={"usage": 109, "limit": 100, "quota_limiting_suspended_until": 1611705600},
            )
            self.organization.save()
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert quota_limited_orgs["events"] == {org_id: 1612137599}
            assert quota_limiting_suspended_orgs["events"] == {}
            self.organization.refresh_from_db()

            assert_other_resources_not_limited(quota_limited_orgs, quota_limiting_suspended_orgs)

            assert self.organization.usage == create_usage_summary(
                events={"usage": 109, "limit": 100, "todays_usage": 0, "quota_limited_until": 1612137599}
            )

            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]

        # Increase trust score. Their quota limiting suspension expiration should not update.
        with freeze_time("2021-01-25T00:00:00Z"):
            assert self.redis_client.delete(f"@posthog/quota-limits/events")

            self.organization.customer_trust_scores = {
                "events": 10,
                "exceptions": 0,
                "recordings": 0,
                "rows_synced": 0,
                "feature_flag_requests": 0,
                QuotaResource.API_QUERIES.value: 0,
                "survey_responses": 0,
            }
            self.organization.usage = create_usage_summary(
                events={"usage": 109, "limit": 100, "quota_limiting_suspended_until": 1611705600},
            )
            self.organization.save()
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert_other_resources_not_limited(quota_limited_orgs, quota_limiting_suspended_orgs)
            assert quota_limited_orgs["events"] == {}
            assert quota_limiting_suspended_orgs["events"] == {org_id: 1611705600}
            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]

            # Reset, quota limiting should be suspended for 3 days.
            self.organization.customer_trust_scores = {
                "events": 10,
                "exceptions": 0,
                "recordings": 0,
                "rows_synced": 0,
                "feature_flag_requests": 0,
                QuotaResource.API_QUERIES.value: 0,
                "survey_responses": 0,
            }
            self.organization.usage = create_usage_summary(
                events={"usage": 109, "limit": 100},
            )
            self.organization.save()
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert_other_resources_not_limited(quota_limited_orgs, quota_limiting_suspended_orgs)
            assert quota_limited_orgs["events"] == {}
            assert quota_limiting_suspended_orgs["events"] == {org_id: 1611878400}
            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]

            # Decrease the trust score to 0. Quota limiting should immediately take effect.
            self.organization.customer_trust_scores = zero_trust_scores()
            self.organization.usage = create_usage_summary(
                events={"usage": 109, "limit": 100, "quota_limiting_suspended_until": 1611705600},
            )
            self.organization.save()
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert_other_resources_not_limited(quota_limited_orgs, quota_limiting_suspended_orgs)
            assert quota_limited_orgs["events"] == {org_id: 1612137599}
            assert quota_limiting_suspended_orgs["events"] == {}
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]

        with freeze_time("2021-01-28T00:00:00Z"):
            self.redis_client.delete(f"@posthog/quota-limits/events")

            # Quota limiting suspension date set in previous billing period, update to new suspension expiration
            self.organization.customer_trust_scores = {
                "events": 10,
                "exceptions": 0,
                "recordings": 0,
                "rows_synced": 0,
                "feature_flag_requests": 0,
                QuotaResource.API_QUERIES.value: 0,
                "survey_responses": 0,
            }
            self.organization.usage = create_usage_summary(
                events={"usage": 109, "limit": 100, "quota_limiting_suspended_until": 1611705600},
                period=["2021-01-27T00:00:00Z", "2021-01-31T23:59:59Z"],
            )
            self.organization.save()

            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert_other_resources_not_limited(quota_limited_orgs, quota_limiting_suspended_orgs)
            assert quota_limited_orgs["events"] == {}
            assert quota_limiting_suspended_orgs["events"] == {org_id: 1612137600}
            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/events", 0, -1) == [
                self.team.api_token.encode("UTF-8")
            ]

    def test_set_org_usage_summary_updates_correctly(self):
        self.organization.usage = {
            "events": {"usage": 99, "limit": 100},
            "exceptions": {"usage": 10, "limit": 100},
            "recordings": {"usage": 1, "limit": 100},
            "rows_synced": {"usage": 5, "limit": 100},
            "feature_flag_requests": {"usage": 5, "limit": 100},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            "survey_responses": {"usage": 10, "limit": 100},
        }
        self.organization.save()

        new_usage = {
            "events": {"usage": 100, "limit": 100},
            "exceptions": {"usage": 20, "limit": 100},
            "recordings": {"usage": 2, "limit": 100},
            "rows_synced": {"usage": 6, "limit": 100},
            "feature_flag_requests": {"usage": 6, "limit": 100},
            "period": [
                "2021-01-01T00:00:00Z",
                "2021-01-31T23:59:59Z",
            ],
            "survey_responses": {"usage": 20, "limit": 100},
        }

        assert set_org_usage_summary(self.organization, new_usage=cast(OrganizationUsageInfo, new_usage))

        assert self.organization.usage == {
            "events": {"usage": 100, "limit": 100, "todays_usage": 0},
            "exceptions": {"usage": 20, "limit": 100, "todays_usage": 0},
            "recordings": {"usage": 2, "limit": 100, "todays_usage": 0},
            "rows_synced": {"usage": 6, "limit": 100, "todays_usage": 0},
            "feature_flag_requests": {"usage": 6, "limit": 100, "todays_usage": 0},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            "survey_responses": {"usage": 20, "limit": 100, "todays_usage": 0},
        }

    def test_set_org_usage_summary_does_nothing_if_the_same(self):
        self.organization.usage = {
            "events": {"usage": 99, "limit": 100, "todays_usage": 10},
            "exceptions": {"usage": 10, "limit": 100, "todays_usage": 50},
            "recordings": {"usage": 1, "limit": 100, "todays_usage": 11},
            "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 11},
            "feature_flag_requests": {"usage": 5, "limit": 100, "todays_usage": 11},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            "survey_responses": {"usage": 10, "limit": 100, "todays_usage": 50},
        }
        self.organization.save()

        new_usage = {
            "events": {"usage": 99, "limit": 100},
            "exceptions": {"usage": 10, "limit": 100},
            "recordings": {"usage": 1, "limit": 100},
            "rows_synced": {"usage": 5, "limit": 100},
            "feature_flag_requests": {"usage": 5, "limit": 100},
            "period": [
                "2021-01-01T00:00:00Z",
                "2021-01-31T23:59:59Z",
            ],
            "survey_responses": {"usage": 10, "limit": 100},
        }

        assert not set_org_usage_summary(self.organization, new_usage=cast(OrganizationUsageInfo, new_usage))

        assert self.organization.usage == {
            "events": {"usage": 99, "limit": 100, "todays_usage": 10},
            "exceptions": {"usage": 10, "limit": 100, "todays_usage": 50},
            "recordings": {"usage": 1, "limit": 100, "todays_usage": 11},
            "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 11},
            "feature_flag_requests": {"usage": 5, "limit": 100, "todays_usage": 11},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            "survey_responses": {"usage": 10, "limit": 100, "todays_usage": 50},
        }

    def test_set_org_usage_summary_updates_todays_usage(self):
        self.organization.usage = {
            "events": {"usage": 99, "limit": 100, "todays_usage": 10},
            "exceptions": {"usage": 10, "limit": 100, "todays_usage": 50},
            "recordings": {"usage": 1, "limit": 100, "todays_usage": 11},
            "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 11},
            "feature_flag_requests": {"usage": 5, "limit": 100, "todays_usage": 11},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            "survey_responses": {"usage": 10, "limit": 100, "todays_usage": 50},
        }
        self.organization.save()

        assert set_org_usage_summary(
            self.organization,
            todays_usage=cast(
                UsageCounters,
                {
                    "events": 20,
                    "exceptions": 51,
                    "recordings": 21,
                    "rows_synced": 21,
                    "feature_flag_requests": 21,
                    "survey_responses": 21,
                },
            ),
        )

        assert self.organization.usage == {
            "events": {"usage": 99, "limit": 100, "todays_usage": 20},
            "exceptions": {"usage": 10, "limit": 100, "todays_usage": 51},
            "recordings": {"usage": 1, "limit": 100, "todays_usage": 21},
            "rows_synced": {"usage": 5, "limit": 100, "todays_usage": 21},
            "feature_flag_requests": {"usage": 5, "limit": 100, "todays_usage": 21},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            "survey_responses": {"usage": 10, "limit": 100, "todays_usage": 21},
        }

    def test_org_quota_limited_until(self):
        self.organization.usage = None
        self.organization.customer_trust_scores = zero_trust_scores()
        previously_quota_limited_team_tokens_events = list_limited_team_attributes(
            QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_exceptions = list_limited_team_attributes(
            QuotaResource.EXCEPTIONS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_recordings = list_limited_team_attributes(
            QuotaResource.RECORDINGS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_rows_synced = list_limited_team_attributes(
            QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_surveys = list_limited_team_attributes(
            QuotaResource.SURVEY_RESPONSES, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_ai_credits = list_limited_team_attributes(
            QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
            )
            is None
        )

        self.organization.usage = {
            "events": {"usage": 99, "limit": 100},
            "exceptions": {"usage": 10, "limit": 100},
            "recordings": {"usage": 1, "limit": 100},
            "rows_synced": {"usage": 99, "limit": 100},
            "feature_flag_requests": {"usage": 99, "limit": 100},
            "api_queries_read_bytes": {"usage": 99, "limit": 100},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            "survey_responses": {"usage": 10, "limit": 100},
            "ai_credits": {"usage": 10, "limit": 100},
        }

        # Not over quota
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
            )
            is None
        )

        # Over quota
        self.organization.usage["events"]["usage"] = 120
        assert org_quota_limited_until(
            self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
        ) == {
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }

        # At quota limit with today's usage
        self.organization.usage["events"]["usage"] = 90
        self.organization.usage["events"]["todays_usage"] = 10
        assert org_quota_limited_until(
            self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
        ) == {
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }

        # No limit clears quota_limited_until
        self.organization.usage["events"]["limit"] = None
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
            )
            is None
        )

        # Not over quota
        self.organization.usage["exceptions"]["usage"] = 99
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.EXCEPTIONS, previously_quota_limited_team_tokens_exceptions
            )
            is None
        )

        # Over quota
        self.organization.usage["exceptions"]["usage"] = 101
        assert org_quota_limited_until(
            self.organization, QuotaResource.EXCEPTIONS, previously_quota_limited_team_tokens_exceptions
        ) == {
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }

        # Under limit + buffer
        self.organization.usage["recordings"]["usage"] = 1099
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.RECORDINGS, previously_quota_limited_team_tokens_recordings
            )
            is None
        )

        # Over limit + buffer
        self.organization.usage["recordings"]["usage"] = 1100
        assert org_quota_limited_until(
            self.organization, QuotaResource.RECORDINGS, previously_quota_limited_team_tokens_recordings
        ) == {
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }

        # Not over quota
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.ROWS_SYNCED, previously_quota_limited_team_tokens_rows_synced
            )
            is None
        )

        # Over quota
        self.organization.usage["rows_synced"]["usage"] = 101
        assert org_quota_limited_until(
            self.organization, QuotaResource.ROWS_SYNCED, previously_quota_limited_team_tokens_rows_synced
        ) == {
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }

        # Not over quota
        self.organization.usage["survey_responses"]["usage"] = 99
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.SURVEY_RESPONSES, previously_quota_limited_team_tokens_surveys
            )
            is None
        )

        # Over quota
        self.organization.usage["survey_responses"]["usage"] = 101
        assert org_quota_limited_until(
            self.organization, QuotaResource.SURVEY_RESPONSES, previously_quota_limited_team_tokens_surveys
        ) == {
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }

        # Not over quota
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.AI_CREDITS, previously_quota_limited_team_tokens_ai_credits
            )
            is None
        )

        # Over quota
        self.organization.usage["ai_credits"]["usage"] = 101
        assert org_quota_limited_until(
            self.organization, QuotaResource.AI_CREDITS, previously_quota_limited_team_tokens_ai_credits
        ) == {
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }
        with freeze_time("2021-01-25T00:00:00Z"):
            # Different trust scores so different grace periods
            self.organization.customer_trust_scores = {
                QuotaResource.EVENTS.value: 7,
                QuotaResource.EXCEPTIONS.value: 7,
                QuotaResource.RECORDINGS.value: 3,
                QuotaResource.ROWS_SYNCED.value: 10,
                QuotaResource.FEATURE_FLAG_REQUESTS.value: 10,
                QuotaResource.API_QUERIES.value: 10,
                QuotaResource.SURVEY_RESPONSES.value: 7,
                QuotaResource.AI_CREDITS.value: 10,
            }

            # Update to be over quota on all resources
            self.organization.usage = {
                "events": {"usage": 101, "limit": 100},
                "exceptions": {"usage": 101, "limit": 100},
                "recordings": {"usage": 1101, "limit": 100},  # overage buffer of 1000
                "rows_synced": {"usage": 101, "limit": 100},
                "feature_flag_requests": {"usage": 101, "limit": 100},
                "api_queries_read_bytes": {"usage": 101, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
                "survey_responses": {"usage": 101, "limit": 100},
                "ai_credits": {"usage": 101, "limit": 100},
            }

            # All resources over quota
            assert org_quota_limited_until(
                self.organization, QuotaResource.ROWS_SYNCED, previously_quota_limited_team_tokens_rows_synced
            ) == {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": 1611878400,  # grace period 3 days
            }
            assert org_quota_limited_until(
                self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
            ) == {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": 1611705600,  # grace period 1 day
            }
            assert org_quota_limited_until(
                self.organization, QuotaResource.EXCEPTIONS, previously_quota_limited_team_tokens_exceptions
            ) == {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": 1611705600,  # grace period 1 day
            }
            assert org_quota_limited_until(
                self.organization, QuotaResource.RECORDINGS, previously_quota_limited_team_tokens_recordings
            ) == {
                "quota_limited_until": 1612137599,  # no grace period
                "quota_limiting_suspended_until": None,
            }
            assert org_quota_limited_until(
                self.organization, QuotaResource.API_QUERIES, previously_quota_limited_team_tokens_recordings
            ) == {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": 1611878400,  # grace period 3 days
            }
            assert org_quota_limited_until(
                self.organization, QuotaResource.SURVEY_RESPONSES, previously_quota_limited_team_tokens_surveys
            ) == {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": 1611705600,  # grace period 1 day
            }
            # AI credits have NO grace period - immediately limit
            assert org_quota_limited_until(
                self.organization, QuotaResource.AI_CREDITS, previously_quota_limited_team_tokens_ai_credits
            ) == {
                "quota_limited_until": 1612137599,
                "quota_limiting_suspended_until": None,
            }

    def test_over_quota_but_not_dropped_org(self):
        self.organization.usage = None
        previously_quota_limited_team_tokens_events = list_limited_team_attributes(
            QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_exceptions = list_limited_team_attributes(
            QuotaResource.EXCEPTIONS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_recordings = list_limited_team_attributes(
            QuotaResource.RECORDINGS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_rows_synced = list_limited_team_attributes(
            QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_surveys = list_limited_team_attributes(
            QuotaResource.SURVEY_RESPONSES, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limited_team_tokens_ai_credits = list_limited_team_attributes(
            QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.EVENTS, previously_quota_limited_team_tokens_events
            )
            is None
        )

        self.organization.usage = {
            "events": {"usage": 100, "limit": 90},
            "exceptions": {"usage": 100, "limit": 90},
            "recordings": {"usage": 100, "limit": 90},
            "rows_synced": {"usage": 100, "limit": 90},
            "feature_flag_requests": {"usage": 100, "limit": 90},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            "survey_responses": {"usage": 10, "limit": 100},
            "ai_credits": {"usage": 100, "limit": 90},
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
                self.organization, QuotaResource.EXCEPTIONS, previously_quota_limited_team_tokens_exceptions
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
        assert (
            org_quota_limited_until(
                self.organization, QuotaResource.SURVEY_RESPONSES, previously_quota_limited_team_tokens_surveys
            )
            is None
        )
        # AI credits ignore never_drop_data - should still be limited
        assert org_quota_limited_until(
            self.organization, QuotaResource.AI_CREDITS, previously_quota_limited_team_tokens_ai_credits
        ) == {
            "quota_limited_until": 1612137599,
            "quota_limiting_suspended_until": None,
        }

        # reset for subsequent tests
        self.organization.never_drop_data = False

    def test_update_org_billing_quotas(self):
        with freeze_time("2021-01-01T12:59:59Z"):
            other_team = create_team(organization=self.organization)

            now = timezone.now().timestamp()

            replace_limited_team_tokens(
                QuotaResource.EVENTS,
                {"1234": int(now + 10000)},
                QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
            )
            replace_limited_team_tokens(
                QuotaResource.EXCEPTIONS,
                {"5678": int(now + 10000)},
                QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
            )
            replace_limited_team_tokens(
                QuotaResource.ROWS_SYNCED,
                {"1337": int(now + 10000)},
                QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
            )
            replace_limited_team_tokens(
                QuotaResource.SURVEY_RESPONSES,
                {"5678": int(now + 10000)},
                QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
            )
            self.organization.usage = {
                "events": {"usage": 99, "limit": 100},
                "exceptions": {"usage": 10, "limit": 100},
                "recordings": {"usage": 1, "limit": 100},
                "rows_synced": {"usage": 35, "limit": 100},
                "feature_flag_requests": {"usage": 5, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
                "survey_responses": {"usage": 10, "limit": 100},
            }

            update_org_billing_quotas(self.organization)
            assert list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY) == [
                "1234"
            ]
            assert list_limited_team_attributes(
                QuotaResource.EXCEPTIONS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            ) == ["5678"]
            assert list_limited_team_attributes(
                QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            ) == ["1337"]
            assert list_limited_team_attributes(
                QuotaResource.SURVEY_RESPONSES, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            ) == ["5678"]

            self.organization.usage["events"]["usage"] = 120
            self.organization.usage["exceptions"]["usage"] = 120
            self.organization.usage["rows_synced"]["usage"] = 120
            self.organization.usage["survey_responses"]["usage"] = 120
            update_org_billing_quotas(self.organization)
            assert sorted(
                list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1234", self.team.api_token, other_team.api_token])
            assert sorted(
                list_limited_team_attributes(QuotaResource.EXCEPTIONS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["5678", self.team.api_token, other_team.api_token])

            # rows_synced uses teams, not tokens
            assert sorted(
                list_limited_team_attributes(QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1337", str(self.team.api_token), str(other_team.api_token)])
            assert sorted(
                list_limited_team_attributes(
                    QuotaResource.SURVEY_RESPONSES, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
                )
            ) == sorted(["5678", self.team.api_token, other_team.api_token])

            self.organization.usage["events"]["usage"] = 80
            self.organization.usage["exceptions"]["usage"] = 80
            self.organization.usage["rows_synced"]["usage"] = 36
            self.organization.usage["survey_responses"]["usage"] = 80
            update_org_billing_quotas(self.organization)
            assert sorted(
                list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1234"])
            assert sorted(
                list_limited_team_attributes(QuotaResource.EXCEPTIONS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["5678"])
            assert sorted(
                list_limited_team_attributes(QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1337"])
            assert sorted(
                list_limited_team_attributes(
                    QuotaResource.SURVEY_RESPONSES, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
                )
            ) == sorted(["5678"])

            self.organization.customer_trust_scores = {
                "events": 10,
                "exceptions": 10,
                "recordings": 0,
                "rows_synced": 7,
                "feature_flag_requests": 10,
                QuotaResource.API_QUERIES.value: 10,
                "survey_responses": 10,
            }
            self.organization.save()

            self.organization.usage["events"]["usage"] = 120
            self.organization.usage["exceptions"]["usage"] = 120
            self.organization.usage["rows_synced"]["usage"] = 120
            self.organization.usage["survey_responses"]["usage"] = 120
            update_org_billing_quotas(self.organization)
            assert sorted(
                list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1234"])
            assert sorted(
                list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY)
            ) == sorted([self.team.api_token, other_team.api_token])

            assert sorted(
                list_limited_team_attributes(QuotaResource.EXCEPTIONS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["5678"])
            assert sorted(
                list_limited_team_attributes(QuotaResource.EXCEPTIONS, QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY)
            ) == sorted([str(self.team.api_token), str(other_team.api_token)])

            # rows_synced uses teams, not tokens
            assert sorted(
                list_limited_team_attributes(QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1337"])
            assert sorted(
                list_limited_team_attributes(
                    QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY
                )
            ) == sorted([str(self.team.api_token), str(other_team.api_token)])
            assert sorted(
                list_limited_team_attributes(
                    QuotaResource.SURVEY_RESPONSES, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
                )
            ) == sorted(["5678"])
            assert sorted(
                list_limited_team_attributes(
                    QuotaResource.SURVEY_RESPONSES, QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY
                )
            ) == sorted([str(self.team.api_token), str(other_team.api_token)])

            self.organization.usage["events"]["usage"] = 80
            self.organization.usage["exceptions"]["usage"] = 80
            self.organization.usage["rows_synced"]["usage"] = 36
            self.organization.usage["survey_responses"]["usage"] = 80
            update_org_billing_quotas(self.organization)
            assert sorted(
                list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1234"])
            assert sorted(
                list_limited_team_attributes(QuotaResource.EXCEPTIONS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["5678"])
            assert sorted(
                list_limited_team_attributes(QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            ) == sorted(["1337"])
            assert sorted(
                list_limited_team_attributes(
                    QuotaResource.SURVEY_RESPONSES, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
                )
            ) == sorted(["5678"])

    @patch("ee.billing.quota_limiting.capture_exception")
    def test_get_team_attribute_by_quota_resource(self, mock_capture):
        Team.objects.all().delete()

        team1 = Team.objects.create(organization=self.organization, api_token="token1")
        team2 = Team.objects.create(organization=self.organization, api_token="token2")

        tokens = get_team_attribute_by_quota_resource(self.organization)

        self.assertEqual(set(tokens), {"token1", "token2"})

        team1.delete()
        team2.delete()

        Team.objects.create(organization=self.organization, api_token="")

        tokens = get_team_attribute_by_quota_resource(self.organization)

        self.assertEqual(tokens, [])
        mock_capture.assert_called_once()

        call_args = mock_capture.call_args
        self.assertEqual(str(call_args[0][0]), "quota_limiting: No team tokens found for organization")
        self.assertEqual(call_args[0][1], {"organization_id": self.organization.id})

    def test_feature_flags_quota_limiting(self):
        with self.settings(USE_TZ=False), freeze_time("2021-01-25T00:00:00Z"):
            self.organization.usage = {
                "events": {"usage": 10, "limit": 100},
                "exceptions": {"usage": 10, "limit": 100},
                "recordings": {"usage": 10, "limit": 100},
                "rows_synced": {"usage": 10, "limit": 100},
                "feature_flag_requests": {"usage": 110, "limit": 100},
                "api_queries_read_bytes": {"usage": 10, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
                "survey_responses": {"usage": 10, "limit": 100},
            }
            self.organization.customer_trust_scores = zero_trust_scores()
            self.organization.save()

            # Test that feature flags always get 2-day grace period even with trust score 0
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            org_id = str(self.organization.id)
            assert quota_limited_orgs["feature_flag_requests"] == {}
            assert quota_limiting_suspended_orgs["feature_flag_requests"] == {org_id: 1611792000}  # 2 day suspension
            assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                f"@posthog/quota-limiting-suspended/feature_flag_requests", 0, -1
            )

            # Test medium trust score (7) - should still get 2 day suspension due to special case
            self.organization.customer_trust_scores["feature_flag_requests"] = 7
            self.organization.usage["feature_flag_requests"] = {"usage": 110, "limit": 100}
            self.organization.save()
            self.redis_client.delete(f"@posthog/quota-limiting-suspended/feature_flag_requests")

            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert quota_limited_orgs["feature_flag_requests"] == {}
            assert quota_limiting_suspended_orgs["feature_flag_requests"] == {org_id: 1611792000}  # 2 day suspension
            assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                f"@posthog/quota-limiting-suspended/feature_flag_requests", 0, -1
            )

            # Test suspension expiry leads to limiting after 2 days
            with freeze_time("2021-01-28T00:00:00Z"):  # 3 days later
                quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
                assert quota_limited_orgs["feature_flag_requests"] == {org_id: 1612137599}
                assert quota_limiting_suspended_orgs["feature_flag_requests"] == {}
                assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                    f"@posthog/quota-limits/feature_flag_requests", 0, -1
                )

            # Test medium-high trust score (10) - should get 3 day suspension
            with freeze_time("2021-01-25T00:00:00Z"):
                self.organization.customer_trust_scores["feature_flag_requests"] = 10
                self.organization.usage["feature_flag_requests"] = {"usage": 110, "limit": 100}
                self.organization.save()
                self.redis_client.delete(f"@posthog/quota-limits/feature_flag_requests")

                quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
                assert quota_limited_orgs["feature_flag_requests"] == {}
                assert quota_limiting_suspended_orgs["feature_flag_requests"] == {
                    org_id: 1611878400
                }  # 3 day suspension
                assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                    f"@posthog/quota-limiting-suspended/feature_flag_requests", 0, -1
                )

            # Test never_drop_data organization is not limited
            self.organization.customer_trust_scores["feature_flag_requests"] = 0
            self.organization.never_drop_data = True
            self.organization.save()
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert quota_limited_orgs["feature_flag_requests"] == {}
            assert quota_limiting_suspended_orgs["feature_flag_requests"] == {}
            assert self.redis_client.zrange(f"@posthog/quota-limits/feature_flag_requests", 0, -1) == []
            assert self.redis_client.zrange(f"@posthog/quota-limiting-suspended/feature_flag_requests", 0, -1) == []

    def test_feature_flags_always_get_2_day_grace_period(self):
        """Test that feature flags always get at least a 2-day grace period, or their trust score grace period if higher"""
        with self.settings(USE_TZ=False), freeze_time("2021-01-25T00:00:00Z"):
            self.organization.usage = {
                "events": {"usage": 10, "limit": 100},
                "exceptions": {"usage": 10, "limit": 100},
                "recordings": {"usage": 10, "limit": 100},
                "rows_synced": {"usage": 10, "limit": 100},
                "feature_flag_requests": {"usage": 110, "limit": 100},
                "api_queries_read_bytes": {"usage": 10, "limit": 100},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
                "survey_responses": {"usage": 10, "limit": 100},
            }
            org_id = str(self.organization.id)

            # Test different trust scores get at least 2-day grace period for feature flags
            test_cases = [
                (0, 1611792000),  # Trust score 0 -> 2 days (1611792000 = 2021-01-27T00:00:00Z)
                (3, 1611792000),  # Trust score 3 -> 2 days (normally 0, but minimum is 2)
                (7, 1611792000),  # Trust score 7 -> 2 days (normally 1, but minimum is 2)
                (10, 1611878400),  # Trust score 10 -> 3 days (normally 3, which is > 2)
                (15, 1612051200),  # Trust score 15 -> 5 days (normally 5, which is > 2)
            ]

            for trust_score, expected_timestamp in test_cases:
                self.organization.customer_trust_scores = {"feature_flag_requests": trust_score}
                self.organization.save()

                # Clear any existing Redis state
                self.redis_client.delete(f"@posthog/quota-limits/feature_flag_requests")
                self.redis_client.delete(f"@posthog/quota-limiting-suspended/feature_flag_requests")

                quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()

                # Should get at least 2-day grace period, or more if trust score allows
                assert quota_limited_orgs["feature_flag_requests"] == {}, (
                    f"Trust score {trust_score} should not immediately limit"
                )
                assert quota_limiting_suspended_orgs["feature_flag_requests"] == {org_id: expected_timestamp}, (
                    f"Trust score {trust_score} should get appropriate grace period"
                )
                assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                    f"@posthog/quota-limiting-suspended/feature_flag_requests", 0, -1
                )

    def test_api_queries_quota_limiting(self):
        with self.settings(USE_TZ=False), freeze_time("2021-01-25T00:00:00Z"):
            self.organization.usage = {
                "events": {"usage": 10, "limit": 100},
                "recordings": {"usage": 10, "limit": 100},
                "rows_synced": {"usage": 10, "limit": 100},
                "feature_flag_requests": {"usage": 10, "limit": 100},
                "api_queries_read_bytes": {"usage": 1100, "limit": 1000},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            trust_key = QuotaResource.API_QUERIES.value
            self.organization.customer_trust_scores = {
                "events": 0,
                "recordings": 0,
                "rows_synced": 0,
                "feature_flag_requests": 0,
                trust_key: 0,
            }
            self.organization.save()

            # Test immediate limiting with trust score 0
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            org_id = str(self.organization.id)
            assert quota_limited_orgs["api_queries_read_bytes"] == {org_id: 1612137599}
            assert quota_limiting_suspended_orgs["api_queries_read_bytes"] == {}
            assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                f"@posthog/quota-limits/api_queries_read_bytes", 0, -1
            )

            # Test medium trust score (7) - should get 1 day suspension
            self.organization.customer_trust_scores[trust_key] = 7
            self.organization.usage["api_queries_read_bytes"] = {"usage": 1100, "limit": 1000}
            self.organization.save()
            self.redis_client.delete(f"@posthog/quota-limits/api_queries_read_bytes")

            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert quota_limited_orgs["api_queries_read_bytes"] == {}
            assert quota_limiting_suspended_orgs["api_queries_read_bytes"] == {org_id: 1611705600}  # 1 day suspension
            assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                f"@posthog/quota-limiting-suspended/api_queries_read_bytes", 0, -1
            )

            # Test suspension expiry leads to limiting
            with freeze_time("2021-01-27T00:00:00Z"):  # 2 days later
                quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
                assert quota_limited_orgs["api_queries_read_bytes"] == {org_id: 1612137599}
                assert quota_limiting_suspended_orgs["api_queries_read_bytes"] == {}
                assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                    f"@posthog/quota-limits/api_queries_read_bytes", 0, -1
                )

            # Test medium-high trust score (10) - should get 3 day suspension
            with freeze_time("2021-01-25T00:00:00Z"):
                self.organization.customer_trust_scores[trust_key] = 10
                self.organization.usage["api_queries_read_bytes"] = {"usage": 110, "limit": 100}
                self.organization.save()
                self.redis_client.delete(f"@posthog/quota-limits/api_queries_read_bytes")

                quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
                assert quota_limited_orgs["api_queries_read_bytes"] == {}
                assert quota_limiting_suspended_orgs["api_queries_read_bytes"] == {
                    org_id: 1611878400
                }  # 3 day suspension
                assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                    f"@posthog/quota-limiting-suspended/api_queries_read_bytes", 0, -1
                )

            # Test high trust score (15) - should get 5 day suspension
            with freeze_time("2021-01-25T00:00:00Z"):
                self.organization.customer_trust_scores[trust_key] = 15
                self.organization.usage["api_queries_read_bytes"] = {"usage": 110, "limit": 100}
                self.organization.save()
                self.redis_client.delete(f"@posthog/quota-limits/api_queries_read_bytes")

                quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
                assert quota_limited_orgs["api_queries_read_bytes"] == {}
                assert quota_limiting_suspended_orgs["api_queries_read_bytes"] == {
                    org_id: 1612051200
                }  # 5 day suspension
                assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                    f"@posthog/quota-limiting-suspended/api_queries_read_bytes", 0, -1
                )

            # Test never_drop_data organization is not limited
            self.organization.customer_trust_scores[trust_key] = 0
            self.organization.never_drop_data = True
            self.organization.save()
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert quota_limited_orgs["api_queries_read_bytes"] == {}
            assert quota_limiting_suspended_orgs["api_queries_read_bytes"] == {}
            assert self.redis_client.zrange(f"@posthog/quota-limits/api_queries_read_bytes", 0, -1) == []

    def test_ai_credits_quota_limiting(self):
        """Test that AI credits have no grace period and immediately limit regardless of trust score."""
        with self.settings(USE_TZ=False), freeze_time("2021-01-25T00:00:00Z"):
            self.organization.usage = {
                "events": {"usage": 10, "limit": 100},
                "recordings": {"usage": 10, "limit": 100},
                "rows_synced": {"usage": 10, "limit": 100},
                "feature_flag_requests": {"usage": 10, "limit": 100},
                "ai_credits": {"usage": 1100, "limit": 1000},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            trust_key = QuotaResource.AI_CREDITS.value
            org_id = str(self.organization.id)

            # Test immediate limiting with trust score 0 - NO grace period
            self.organization.customer_trust_scores = {
                "events": 0,
                "recordings": 0,
                "rows_synced": 0,
                "feature_flags": 0,
                trust_key: 0,
            }
            self.organization.save()

            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert quota_limited_orgs["ai_credits"] == {org_id: 1612137599}
            assert quota_limiting_suspended_orgs["ai_credits"] == {}
            assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                f"@posthog/quota-limits/ai_credits", 0, -1
            )

            # Test medium trust score (7) - should STILL immediately limit, NO grace period
            self.organization.customer_trust_scores[trust_key] = 7
            self.organization.usage["ai_credits"] = {"usage": 1100, "limit": 1000}
            self.organization.save()
            self.redis_client.delete(f"@posthog/quota-limits/ai_credits")

            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert quota_limited_orgs["ai_credits"] == {org_id: 1612137599}
            assert quota_limiting_suspended_orgs["ai_credits"] == {}
            assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                f"@posthog/quota-limits/ai_credits", 0, -1
            )

            # Test medium-high trust score (10) - should STILL immediately limit, NO grace period
            self.organization.customer_trust_scores[trust_key] = 10
            self.organization.usage["ai_credits"] = {"usage": 1100, "limit": 1000}
            self.organization.save()
            self.redis_client.delete(f"@posthog/quota-limits/ai_credits")

            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert quota_limited_orgs["ai_credits"] == {org_id: 1612137599}
            assert quota_limiting_suspended_orgs["ai_credits"] == {}
            assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                f"@posthog/quota-limits/ai_credits", 0, -1
            )

            # Test high trust score (15) - should STILL immediately limit, NO grace period
            self.organization.customer_trust_scores[trust_key] = 15
            self.organization.usage["ai_credits"] = {"usage": 1100, "limit": 1000}
            self.organization.save()
            self.redis_client.delete(f"@posthog/quota-limits/ai_credits")

            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert quota_limited_orgs["ai_credits"] == {org_id: 1612137599}
            assert quota_limiting_suspended_orgs["ai_credits"] == {}
            assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                f"@posthog/quota-limits/ai_credits", 0, -1
            )

            # Test that never_drop_data does NOT apply to AI credits - still gets limited
            self.organization.customer_trust_scores[trust_key] = 0
            self.organization.never_drop_data = True
            self.organization.save()
            self.redis_client.delete(f"@posthog/quota-limits/ai_credits")

            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()
            assert quota_limited_orgs["ai_credits"] == {org_id: 1612137599}
            assert quota_limiting_suspended_orgs["ai_credits"] == {}
            assert self.team.api_token.encode("UTF-8") in self.redis_client.zrange(
                f"@posthog/quota-limits/ai_credits", 0, -1
            )

    @patch("posthoganalytics.capture")
    @freeze_time("2021-01-25T00:00:00Z")
    def test_quota_limited_until_but_not_over_limit(self, mock_capture) -> None:
        """Test that when a customer is not over the limit but has quota_limited_until set, the suspension is removed."""
        with self.settings(USE_TZ=False):
            # Set up organization with usage below the limit but with quota_limited_until set
            self.organization.usage = {
                "events": {
                    "usage": 80,
                    "limit": 100,
                    "quota_limited_until": 1612137599,  # End of billing period
                },
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()

            # Add the team token to the quota-limits list
            team_token = self.team.api_token.encode("UTF-8")
            self.redis_client.zadd(f"@posthog/quota-limits/events", {team_token: 1612137599})

            # Run the quota limiting check
            quota_limited_orgs, quota_limiting_suspended_orgs, _stats = update_all_orgs_billing_quotas()

            # Verify the organization is no longer quota limited
            assert "events" in quota_limited_orgs
            assert "events" in quota_limiting_suspended_orgs
            assert quota_limited_orgs["events"] == {}
            assert quota_limiting_suspended_orgs["events"] == {}

            # Verify the team token was removed from the quota-limits list
            assert self.redis_client.zrange(f"@posthog/quota-limits/events", 0, -1) == []

            # Verify the organization usage was updated to remove quota_limited_until
            self.organization.refresh_from_db()
            assert self.organization.usage["events"].get("quota_limited_until") is None

            # Find the specific call for org_quota_limited_until with suspension removed
            event = None
            for call in mock_capture.call_args_list:
                if len(call) >= 2 and call[1]["event"] == "org_quota_limited_until":
                    event = call
                    break

            # Verify the correct event was reported
            assert event is not None, "Could not find org_quota_limited_until call with suspension removed"
            assert event[1]["properties"]["current_usage"] == 80
            assert event[1]["properties"]["resource"] == "events"
            assert event[1]["properties"]["quota_limiting_suspended_until"] is None
            assert "organization" in event[1]["groups"]
            assert event[1]["groups"]["organization"] == str(self.organization.id)

    @patch("posthoganalytics.capture")
    @freeze_time("2021-01-25T23:59:59Z")
    def test_quota_limiting_surveys(self, mock_capture) -> None:
        """Test that surveys quota limiting works correctly"""
        with self.settings(USE_TZ=False):
            # Set up usage data with surveys over the limit
            self.organization.usage = {
                "survey_responses": {"usage": 95, "limit": 100, "todays_usage": 10},  # 105 total, over limit of 100
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.customer_trust_scores = {"survey_responses": 0}  # Low trust score
            self.organization.save()

            # Run quota limiting update
            update_org_billing_quotas(self.organization)

            # Verify team token was added to quota limited list
            limited_tokens = list_limited_team_attributes(
                QuotaResource.SURVEY_RESPONSES, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )
            assert self.team.api_token in limited_tokens

            # Verify org usage was updated with quota_limited_until
            self.organization.refresh_from_db()
            assert self.organization.usage["survey_responses"].get("quota_limited_until") is not None

            # Verify analytics event was captured
            mock_capture.assert_called()

            # Check that the correct properties were logged
            org_action_call = None
            for call in mock_capture.call_args_list:
                if len(call) >= 2 and call[1]["event"] == "org_quota_limited_until":
                    org_action_call = call
                    break

            assert org_action_call is not None
            assert org_action_call[1]["properties"]["resource"] == "survey_responses"
            assert org_action_call[1]["properties"]["current_usage"] == 105
            assert org_action_call[1]["properties"]["event"] == "suspended"

    @freeze_time("2021-01-25T23:59:59Z")
    def test_quota_limiting_surveys_under_limit(self) -> None:
        """Test that surveys under quota limit are not restricted"""
        with self.settings(USE_TZ=False):
            # Set up usage data with surveys under the limit
            self.organization.usage = {
                "survey_responses": {"usage": 80, "limit": 100, "todays_usage": 5},  # 85 total, under limit
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()

            # Run quota limiting update
            update_org_billing_quotas(self.organization)

            # Verify team token was NOT added to quota limited list
            limited_tokens = list_limited_team_attributes(
                QuotaResource.SURVEY_RESPONSES, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )
            assert self.team.api_token not in limited_tokens

            # Verify org usage does not have quota_limited_until
            self.organization.refresh_from_db()
            assert self.organization.usage["survey_responses"].get("quota_limited_until") is None

    @freeze_time("2021-01-25T23:59:59Z")
    @patch("posthoganalytics.capture")
    def test_quota_limiting_ai_events(self, mock_capture) -> None:
        """Test that AI events are properly limited when quota exceeded"""
        with self.settings(USE_TZ=False):
            # Set up usage data with AI events over the limit
            self.organization.usage = {
                "llm_events": {"usage": 100, "limit": 100, "todays_usage": 5},  # 105 total, over limit
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()

            # Run quota limiting update
            update_org_billing_quotas(self.organization)

            # Verify team token was added to quota limited list
            limited_tokens = list_limited_team_attributes(
                QuotaResource.LLM_EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )
            assert self.team.api_token in limited_tokens

            # Verify org usage was updated with quota_limited_until
            self.organization.refresh_from_db()
            assert self.organization.usage["llm_events"].get("quota_limited_until") is not None

            # Verify analytics event was captured
            mock_capture.assert_called()

            # Check that the correct properties were logged
            org_action_call = None
            for call in mock_capture.call_args_list:
                if len(call) >= 2 and call[1]["event"] == "org_quota_limited_until":
                    org_action_call = call
                    break

            assert org_action_call is not None
            assert org_action_call[1]["properties"]["resource"] == "llm_events"
            assert org_action_call[1]["properties"]["current_usage"] == 105
            assert org_action_call[1]["properties"]["event"] == "suspended"

    @freeze_time("2021-01-25T23:59:59Z")
    def test_quota_limiting_ai_events_under_limit(self) -> None:
        """Test that AI events under quota limit are not restricted"""
        with self.settings(USE_TZ=False):
            # Set up usage data with AI events under the limit
            self.organization.usage = {
                "llm_events": {"usage": 80, "limit": 100, "todays_usage": 5},  # 85 total, under limit
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()

            # Run quota limiting update
            update_org_billing_quotas(self.organization)

            # Verify team token was NOT added to quota limited list
            limited_tokens = list_limited_team_attributes(
                QuotaResource.LLM_EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )
            assert self.team.api_token not in limited_tokens

            # Verify org usage does not have quota_limited_until
            self.organization.refresh_from_db()
            assert self.organization.usage["llm_events"].get("quota_limited_until") is None

    @freeze_time("2021-01-25T23:59:59Z")
    def test_ai_events_trust_score_tracking(self) -> None:
        """Test trust score updates for AI event limiting"""
        with self.settings(USE_TZ=False):
            # Set up initial trust scores
            self.organization.customer_trust_scores = {
                "events": 0,
                "exceptions": 0,
                "recordings": 0,
                "rows_synced": 0,
                "feature_flag_requests": 0,
                "api_queries_read_bytes": 0,
                "survey_responses": 0,
                "llm_events": 0,
            }
            self.organization.usage = {
                "llm_events": {"usage": 100, "limit": 100, "todays_usage": 5},  # Over limit
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()

            # First run should limit immediately due to trust score 0
            update_org_billing_quotas(self.organization)

            limited_tokens = list_limited_team_attributes(
                QuotaResource.LLM_EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )
            assert self.team.api_token in limited_tokens

            # Increase trust score
            self.organization.customer_trust_scores["llm_events"] = 7
            self.organization.save()

            # Clear the limiting to test suspension behavior
            self.redis_client.delete(f"@posthog/quota-limits/llm_events")
            # Also clear the quota_limited_until field to reset state
            self.organization.usage["llm_events"]["quota_limited_until"] = None
            # Keep over the limit
            self.organization.usage["llm_events"]["todays_usage"] = 5
            self.organization.save()

            # Run again - should be suspended this time
            update_org_billing_quotas(self.organization)

            # Should be in suspended list, not limited list
            limited_tokens = list_limited_team_attributes(
                QuotaResource.LLM_EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )
            assert self.team.api_token not in limited_tokens

            suspended_tokens = list_limited_team_attributes(
                QuotaResource.LLM_EVENTS, QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY
            )
            assert self.team.api_token in suspended_tokens

    @freeze_time("2021-01-25T23:59:59Z")
    def test_ai_events_quota_with_overage_buffer(self) -> None:
        """Test overage buffer behavior for AI events"""
        with self.settings(USE_TZ=False):
            # AI events have 0 overage buffer according to OVERAGE_BUFFER
            self.organization.usage = {
                "llm_events": {"usage": 100, "limit": 100, "todays_usage": 0},  # Exactly at limit
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()

            # Run quota limiting update
            update_org_billing_quotas(self.organization)

            # Should be limited when exactly at limit (>= comparison with 0 buffer means at limit = over limit)
            limited_tokens = list_limited_team_attributes(
                QuotaResource.LLM_EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )
            assert self.team.api_token in limited_tokens

            # Reduce usage to be under limit
            self.organization.usage["llm_events"]["usage"] = 99
            self.organization.save()
            update_org_billing_quotas(self.organization)

            # Now should not be limited
            limited_tokens = list_limited_team_attributes(
                QuotaResource.LLM_EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )
            assert self.team.api_token not in limited_tokens

    @freeze_time("2021-01-25T23:59:59Z")
    @patch("posthoganalytics.capture")
    def test_ai_events_quota_suspension_and_resume(self, mock_capture) -> None:
        """Test suspension and resume mechanics for AI quotas"""
        with self.settings(USE_TZ=False):
            # Start with trust score that allows suspension
            self.organization.customer_trust_scores = {
                "events": 0,
                "exceptions": 0,
                "recordings": 0,
                "rows_synced": 0,
                "feature_flag_requests": 0,
                "api_queries_read_bytes": 0,
                "survey_responses": 0,
                "llm_events": 7,  # High trust score
            }
            self.organization.usage = {
                "llm_events": {"usage": 100, "limit": 100, "todays_usage": 5},  # Over limit
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.save()

            # First run should suspend (trust score 7 gets suspension, not immediate limiting)
            update_org_billing_quotas(self.organization)
            assert self.team.api_token in list_limited_team_attributes(
                QuotaResource.LLM_EVENTS, QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY
            )

            # Now reduce usage below limit to test resume
            self.organization.usage["llm_events"]["todays_usage"] = 0
            self.organization.usage["llm_events"]["usage"] = 90  # Under limit
            self.organization.save()

            # Run again - should clear suspension since under limit
            update_org_billing_quotas(self.organization)
            assert self.team.api_token not in list_limited_team_attributes(
                QuotaResource.LLM_EVENTS, QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY
            )
            assert self.team.api_token not in list_limited_team_attributes(
                QuotaResource.LLM_EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )

            # Verify analytics events were captured
            events_captured = [call[1]["event"] for call in mock_capture.call_args_list if len(call) >= 2]
            assert "org_quota_limited_until" in events_captured  # Should have suspension and removal events

    def test_usage_keys_stay_in_sync(self):
        """
        Ensure QuotaResource, UsageCounters, and OrganizationUsageInfo all use the same keys (except for `period`).
        """
        from posthog.models.organization import OrganizationUsageInfo

        # OrganizationUsageInfo is source of truth (excluding 'period``)
        org_usage_keys = set(OrganizationUsageInfo.__annotations__.keys()) - {"period"}

        quota_resource_keys = {resource.value for resource in QuotaResource}
        usage_counter_keys = set(UsageCounters.__annotations__.keys())

        # Check QuotaResource matches OrganizationUsageInfo
        missing_from_quota = org_usage_keys - quota_resource_keys
        extra_in_quota = quota_resource_keys - org_usage_keys
        assert not missing_from_quota, f"QuotaResource is missing keys from OrganizationUsageInfo: {missing_from_quota}"
        assert not extra_in_quota, f"QuotaResource has extra keys not in OrganizationUsageInfo: {extra_in_quota}"

        # Check UsageCounters matches OrganizationUsageInfo
        missing_from_counters = org_usage_keys - usage_counter_keys
        extra_in_counters = usage_counter_keys - org_usage_keys
        assert not missing_from_counters, (
            f"UsageCounters is missing keys from OrganizationUsageInfo: {missing_from_counters}"
        )
        assert not extra_in_counters, f"UsageCounters has extra keys not in OrganizationUsageInfo: {extra_in_counters}"

    @patch("posthoganalytics.capture")
    @freeze_time("2021-01-25T12:00:00Z")
    def test_update_all_orgs_billing_quotas_refreshes_candidate_orgs_before_decision(self, patch_capture) -> None:
        """
        End-to-end: an over-limit-looking org is identified as a refresh candidate, so a
        concurrent billing webhook that lands after the queries phase but before the org
        loop reaches that row is observed by the per-iteration refresh. The decision and
        targeted writes that follow must not clobber the fresh `usage` / `limit` /
        `period` written by billing.

        This is the customer incident shape: free-tier upgrade fires before the cron's
        per-org iteration would have written the row.
        """
        from posthog.models.organization import Organization

        with self.settings(USE_TZ=False):
            stale_usage = {
                "events": {"usage": 9_999_999, "limit": 10_000, "todays_usage": 0},
                "recordings": {"usage": 0, "limit": 10_000, "todays_usage": 0},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.usage = stale_usage
            self.organization.customer_trust_scores = zero_trust_scores()
            self.organization.save()

            # Create events so the ClickHouse rollup produces a non-zero todays_usage,
            # exercising the targeted patch path. Without events the loop short-circuits
            # before any write.
            distinct_id = str(uuid4())
            for _ in range(5):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=1),
                    team=self.team,
                )
            time.sleep(1)

            fresh_usage = {
                "events": {"usage": 0, "limit": 10_000_000, "todays_usage": 0},
                "recordings": {"usage": 0, "limit": 10_000_000, "todays_usage": 0},
                "period": ["2021-01-15T00:00:00Z", "2021-02-14T23:59:59Z"],
            }

            # Hook the simulated webhook write between the queries phase and the org
            # loop. `list_limited_team_attributes` is called once per resource right
            # before the candidate-detection pass, so wrapping it lands the write at the
            # right moment without patching anything inside the loop itself.
            org_id = self.organization.id
            simulated_webhook_write_count = {"count": 0}

            real_list_limited_team_attributes = list_limited_team_attributes

            def list_then_simulate_webhook(*args, **kwargs):
                if simulated_webhook_write_count["count"] == 0:
                    Organization.objects.filter(id=org_id).update(usage=fresh_usage)
                    simulated_webhook_write_count["count"] += 1
                return real_list_limited_team_attributes(*args, **kwargs)

            with patch(
                "ee.billing.quota_limiting.list_limited_team_attributes",
                side_effect=list_then_simulate_webhook,
            ):
                update_all_orgs_billing_quotas()

            assert simulated_webhook_write_count["count"] == 1, (
                "The simulated webhook hook did not fire — the test no longer covers the "
                "queries-phase-to-loop-start window. Re-anchor the hook to a call site "
                "between the queries phase and the org loop."
            )

            final_org = Organization.objects.get(id=org_id)
            assert final_org.usage["events"]["usage"] == 0, (
                "The per-iteration refresh must observe the webhook's fresh `usage` and "
                "the targeted patch must not clobber it back to the stale snapshot "
                "loaded at the start of the job (Calmio regression)."
            )
            assert final_org.usage["events"]["limit"] == 10_000_000, (
                "Fresh `limit` from the webhook must survive the targeted patch."
            )
            assert final_org.usage["period"] == [
                "2021-01-15T00:00:00Z",
                "2021-02-14T23:59:59Z",
            ], "Fresh `period` from the webhook must survive the targeted patch."

    @patch("posthoganalytics.capture")
    @freeze_time("2021-01-25T12:00:00Z")
    def test_update_all_orgs_billing_quotas_targeted_patch_preserves_concurrent_billing_writes(
        self, patch_capture
    ) -> None:
        """
        End-to-end: even for orgs that are NOT refresh candidates (under limit, no quota
        markers), a billing webhook that lands mid-iteration must survive the per-org
        write. The targeted `jsonb_set` patch only touches `usage[resource][todays_usage]`,
        so billing-owned `usage` / `limit` / `period` are not clobbered.
        """
        from posthog.models.organization import Organization

        with self.settings(USE_TZ=False):
            cached_snapshot = {
                "events": {"usage": 0, "limit": 10_000_000, "todays_usage": 0},
                "recordings": {"usage": 0, "limit": 10_000_000, "todays_usage": 0},
                "period": ["2021-01-15T00:00:00Z", "2021-02-14T23:59:59Z"],
            }
            self.organization.usage = cached_snapshot
            self.organization.customer_trust_scores = zero_trust_scores()
            self.organization.save()

            distinct_id = str(uuid4())
            for _ in range(5):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=1),
                    team=self.team,
                )
            time.sleep(1)

            mid_loop_webhook = {
                "events": {"usage": 0, "limit": 50_000_000, "todays_usage": 0},
                "recordings": {"usage": 0, "limit": 50_000_000, "todays_usage": 0},
                "period": ["2021-01-20T00:00:00Z", "2021-02-19T23:59:59Z"],
            }

            org_id = self.organization.id
            mid_loop_write_count = {"count": 0}
            real_patch = _patch_todays_usage

            def webhook_before_per_org_patch(organization, *args, **kwargs):
                # Land the webhook write between candidate detection (already done) and
                # the targeted per-org patch (about to happen). Subsequent calls pass
                # through unchanged.
                if organization.id == org_id and mid_loop_write_count["count"] == 0:
                    Organization.objects.filter(id=org_id).update(usage=mid_loop_webhook)
                    mid_loop_write_count["count"] += 1
                return real_patch(organization, *args, **kwargs)

            with patch(
                "ee.billing.quota_limiting._patch_todays_usage",
                side_effect=webhook_before_per_org_patch,
            ):
                update_all_orgs_billing_quotas()

            assert mid_loop_write_count["count"] == 1

            final_org = Organization.objects.get(id=org_id)
            assert final_org.usage["period"] == [
                "2021-01-20T00:00:00Z",
                "2021-02-19T23:59:59Z",
            ], "Fresh `period` from the webhook must survive the targeted patch."
            assert final_org.usage["events"]["limit"] == 50_000_000, (
                "Fresh `limit` from the webhook must survive the targeted patch."
            )
            assert final_org.usage["events"]["todays_usage"] == 5, (
                "Targeted patch must still write the cron's `todays_usage` for the resource."
            )

    @patch("posthoganalytics.capture")
    @freeze_time("2021-01-25T12:00:00Z")
    def test_candidate_refresh_changes_quota_decision(self, patch_capture) -> None:
        """
        End-to-end: the per-iteration refresh must actually change the decision when
        the DB row has moved. Without the refresh, the cached over-limit snapshot
        would cause us to add the team's token to Redis and report the org as
        quota-limited. With the refresh, fresh DB state shows the org is comfortably
        under the (now much higher) limit, so no Redis token is added.
        """
        with self.settings(USE_TZ=False):
            stale_usage = {
                "events": {"usage": 9_999_999, "limit": 10_000, "todays_usage": 0},
                "recordings": {"usage": 0, "limit": 10_000, "todays_usage": 0},
                "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
            }
            self.organization.usage = stale_usage
            self.organization.customer_trust_scores = zero_trust_scores()
            self.organization.save()

            distinct_id = str(uuid4())
            for _ in range(5):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=1),
                    team=self.team,
                )
            time.sleep(1)

            # A billing webhook lands a fresh paid plan with much higher limits before
            # the org loop reaches this org.
            fresh_usage = {
                "events": {"usage": 0, "limit": 10_000_000, "todays_usage": 0},
                "recordings": {"usage": 0, "limit": 10_000_000, "todays_usage": 0},
                "period": ["2021-01-15T00:00:00Z", "2021-02-14T23:59:59Z"],
            }
            org_id = self.organization.id
            simulated_webhook_write_count = {"count": 0}
            real_list_limited_team_attributes = list_limited_team_attributes

            def list_then_simulate_webhook(*args, **kwargs):
                if simulated_webhook_write_count["count"] == 0:
                    Organization.objects.filter(id=org_id).update(usage=fresh_usage)
                    simulated_webhook_write_count["count"] += 1
                return real_list_limited_team_attributes(*args, **kwargs)

            with patch(
                "ee.billing.quota_limiting.list_limited_team_attributes",
                side_effect=list_then_simulate_webhook,
            ):
                quota_limited_orgs, quota_limiting_suspended_orgs, _ = update_all_orgs_billing_quotas()

            # The decision flipped from "limit" (cached) to "no limit" (refreshed).
            assert str(org_id) not in quota_limited_orgs["events"]
            assert str(org_id) not in quota_limiting_suspended_orgs["events"]
            # And no Redis token was added — the team is free to ingest.
            assert self.redis_client.zrange("@posthog/quota-limits/events", 0, -1) == []

    @patch("posthoganalytics.capture")
    @freeze_time("2021-01-25T12:00:00Z")
    def test_limit_decrease_for_non_candidate_uses_stale_snapshot(self, patch_capture) -> None:
        """
        Documents the residual race window the targeted refresh does NOT close: a
        billing-driven *limit decrease* (e.g. a downgrade) that lands after the
        candidate set is computed is not caught this run. The cached `limit` still
        looks high, so the org is not flagged as a candidate, no per-iteration refresh
        happens, and the decision is made against the stale (high-limit) snapshot. The
        next cron run picks it up within ~30 minutes.

        This asserts the current contract directly. When a future change closes the
        race, this test fails loudly with a meaningful diff and the assertion below
        gets flipped in the same PR.
        """
        with self.settings(USE_TZ=False):
            cached_high_limit = {
                "events": {"usage": 0, "limit": 10_000_000, "todays_usage": 0},
                "recordings": {"usage": 0, "limit": 10_000_000, "todays_usage": 0},
                "period": ["2021-01-15T00:00:00Z", "2021-02-14T23:59:59Z"],
            }
            self.organization.usage = cached_high_limit
            self.organization.customer_trust_scores = zero_trust_scores()
            self.organization.save()

            distinct_id = str(uuid4())
            for _ in range(50):
                _create_event(
                    distinct_id=distinct_id,
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=1),
                    team=self.team,
                )
            time.sleep(1)

            # Mid-loop downgrade lands a much lower limit; the 50 events from
            # ClickHouse now exceed it. A candidate-refresh would catch this; a
            # non-candidate path doesn't.
            mid_loop_downgrade = {
                "events": {"usage": 0, "limit": 10, "todays_usage": 0},
                "recordings": {"usage": 0, "limit": 10, "todays_usage": 0},
                "period": ["2021-01-15T00:00:00Z", "2021-02-14T23:59:59Z"],
            }
            org_id = self.organization.id
            mid_loop_write_count = {"count": 0}
            real_patch = _patch_todays_usage

            def webhook_before_per_org_patch(organization, *args, **kwargs):
                if organization.id == org_id and mid_loop_write_count["count"] == 0:
                    Organization.objects.filter(id=org_id).update(usage=mid_loop_downgrade)
                    mid_loop_write_count["count"] += 1
                return real_patch(organization, *args, **kwargs)

            with patch(
                "ee.billing.quota_limiting._patch_todays_usage",
                side_effect=webhook_before_per_org_patch,
            ):
                quota_limited_orgs, _, _ = update_all_orgs_billing_quotas()

            assert mid_loop_write_count["count"] == 1
            # Current contract: the same-run downgrade is missed because the org was
            # never flagged as a candidate (cached limit was high), so no refresh
            # happened and `org_quota_limited_until` ran against the stale snapshot.
            # If this assertion ever fails, the residual race has been closed —
            # flip it to `in quota_limited_orgs["events"]` in the same PR.
            assert str(org_id) not in quota_limited_orgs["events"]


def _full_usage_counters(**overrides: int) -> UsageCounters:
    base = UsageCounters(
        events=0,
        exceptions=0,
        recordings=0,
        rows_synced=0,
        feature_flag_requests=0,
        api_queries_read_bytes=0,
        survey_responses=0,
        llm_events=0,
        ai_credits=0,
        cdp_trigger_events=0,
        rows_exported=0,
        workflow_emails=0,
        workflow_destinations_dispatched=0,
        logs_mb_ingested=0,
    )
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _empty_previously_limited() -> dict[str, list[str]]:
    return {resource.value: [] for resource in QuotaResource}


def _fake_org(usage: dict | None) -> Any:
    org = type("FakeOrg", (), {})()
    org.id = uuid4()
    org.usage = usage
    return org


_PERIOD = ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"]


@override_settings(CLOUD_DEPLOYMENT="US")
class TestIdentifyRefreshCandidates(BaseTest):
    """Isolated unit coverage for `_identify_refresh_candidates`. The cron-loop
    integration tests above also exercise this function but conflate it with the rest
    of the run; these cases cover each candidate-selection branch in isolation."""

    @parameterized.expand(
        [
            (
                "skips_orgs_with_no_usage",
                None,
                _full_usage_counters(),
                [],
                {},
                {},
                False,
            ),
            (
                "skips_orgs_with_usage_but_no_period",
                {"events": {"usage": 5, "limit": 10}},
                _full_usage_counters(),
                [],
                {},
                {},
                False,
            ),
            (
                "flags_orgs_with_existing_quota_marker",
                {
                    "events": {"usage": 0, "limit": 1_000, "quota_limited_until": 1_700_000_000},
                    "period": _PERIOD,
                },
                _full_usage_counters(),
                [],
                {},
                {},
                True,
            ),
            (
                "flags_orgs_with_existing_suspension_marker",
                {
                    "events": {"usage": 0, "limit": 1_000, "quota_limiting_suspended_until": 1_700_000_000},
                    "period": _PERIOD,
                },
                _full_usage_counters(),
                [],
                {},
                {},
                True,
            ),
            (
                "flags_orgs_appearing_newly_over_limit",
                {
                    "events": {"usage": 950, "limit": 1_000, "todays_usage": 0},
                    "period": _PERIOD,
                },
                # 950 cached + 100 today = 1050 >= 1000 + 0 buffer → candidate
                _full_usage_counters(events=100),
                [],
                {},
                {},
                True,
            ),
            (
                "skips_under_limit_orgs_without_markers_or_redis",
                {
                    "events": {"usage": 100, "limit": 1_000, "todays_usage": 0},
                    "period": _PERIOD,
                },
                _full_usage_counters(events=10),
                [],
                {},
                {},
                False,
            ),
            (
                "skips_resources_with_no_limit_set",
                # `limit=None` means the org has no cap on this resource.
                {
                    "events": {"usage": 999_999, "limit": None, "todays_usage": 0},
                    "period": _PERIOD,
                },
                _full_usage_counters(events=999_999),
                [],
                {},
                {},
                False,
            ),
            (
                "flags_orgs_with_team_token_in_redis_limiter_set",
                {
                    "events": {"usage": 10, "limit": 1_000, "todays_usage": 0},
                    "period": _PERIOD,
                },
                _full_usage_counters(),
                ["phc_xyz"],
                {"events": ["phc_xyz"]},
                {},
                True,
            ),
            (
                # Regression: stale entry in the Redis limiter set must flag the org
                # even when `usage[resource]` is missing — otherwise we'd never refresh
                # and never get the chance to clear the stale entry.
                "redis_token_flags_org_with_empty_resource_dict",
                {"period": _PERIOD},
                _full_usage_counters(),
                ["phc_stale"],
                {"events": ["phc_stale"]},
                {},
                True,
            ),
            (
                # Symmetric regression: a stale entry in the suspension Redis set must
                # also flag the org. Without this, a team only present in the suspended
                # set (no overage, no usage marker) would never be re-evaluated and the
                # suspension entry could persist past its grace period.
                "flags_orgs_with_team_token_in_redis_suspended_set",
                {
                    "events": {"usage": 10, "limit": 1_000, "todays_usage": 0},
                    "period": _PERIOD,
                },
                _full_usage_counters(),
                ["phc_susp"],
                {},
                {"events": ["phc_susp"]},
                True,
            ),
            (
                "suspended_redis_token_flags_org_with_empty_resource_dict",
                {"period": _PERIOD},
                _full_usage_counters(),
                ["phc_susp_stale"],
                {},
                {"events": ["phc_susp_stale"]},
                True,
            ),
            (
                # Only `events` is over limit; other resources are well under. The org
                # should still be flagged from the single over-limit resource.
                "multi_resource_partial_overage_flags_from_one_resource",
                {
                    "events": {"usage": 990, "limit": 1_000, "todays_usage": 0},
                    "recordings": {"usage": 0, "limit": 100_000, "todays_usage": 0},
                    "rows_synced": {"usage": 0, "limit": 100_000, "todays_usage": 0},
                    "period": _PERIOD,
                },
                _full_usage_counters(events=20, recordings=5, rows_synced=5),
                [],
                {},
                {},
                True,
            ),
            (
                # Some orgs land with `usage=None` on a resource (legacy/partial init).
                # The check must coerce to 0, not raise or flag on falsy comparisons.
                "usage_value_none_treated_as_zero",
                {
                    "events": {"usage": None, "limit": 1_000, "todays_usage": 0},
                    "period": _PERIOD,
                },
                _full_usage_counters(events=10),
                [],
                {},
                {},
                False,
            ),
            (
                # Recordings get a 1000-event buffer per `OVERAGE_BUFFER`. Cached usage
                # right at the limit is not yet a candidate.
                "recordings_overage_buffer_is_respected",
                {
                    "recordings": {"usage": 1_000, "limit": 1_000, "todays_usage": 0},
                    "period": _PERIOD,
                },
                # 1000 + 999 = 1999, threshold = 1000 + 1000 = 2000
                _full_usage_counters(recordings=999),
                [],
                {},
                {},
                False,
            ),
        ]
    )
    def test_candidate_selection(
        self,
        _name: str,
        usage: dict | None,
        todays: UsageCounters,
        team_tokens: list[str],
        previously_limited_overrides: dict[str, list[str]],
        previously_suspended_overrides: dict[str, list[str]],
        expected_candidate: bool,
    ) -> None:
        org = _fake_org(usage=usage)
        org_id = str(org.id)
        orgs_by_id = {org_id: org}
        todays_usage_report = {org_id: todays}
        teams_by_org = {org_id: team_tokens} if team_tokens else {}

        previously_limited = _empty_previously_limited()
        previously_limited.update(previously_limited_overrides)
        previously_suspended = _empty_previously_limited()
        previously_suspended.update(previously_suspended_overrides)

        candidates = _identify_refresh_candidates(
            orgs_by_id, todays_usage_report, teams_by_org, previously_limited, previously_suspended
        )

        assert candidates == ({org_id} if expected_candidate else set())


@override_settings(CLOUD_DEPLOYMENT="US")
class TestPatchTodaysUsage(BaseTest):
    """Isolated unit coverage for `_patch_todays_usage`. Verifies the targeted-patch
    semantics that protect billing-owned `usage` / `limit` / `period` from being
    clobbered by stale snapshots."""

    def test_returns_false_when_organization_usage_is_none(self) -> None:
        self.organization.usage = None
        self.organization.save()

        changed = _patch_todays_usage(self.organization, _full_usage_counters(events=42))

        assert changed is False

    def test_returns_false_when_no_resources_to_patch(self) -> None:
        # Org has only `period` — no per-resource dicts to patch.
        self.organization.usage = {"period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"]}
        self.organization.save()

        changed = _patch_todays_usage(self.organization, _full_usage_counters(events=42))

        assert changed is False

    def test_returns_false_when_value_is_unchanged(self) -> None:
        self.organization.usage = {
            "events": {"usage": 100, "limit": 1_000, "todays_usage": 7},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.save()
        before_updated_at = self.organization.updated_at

        changed = _patch_todays_usage(self.organization, _full_usage_counters(events=7))

        assert changed is False
        # No SQL UPDATE means `updated_at` should not move.
        self.organization.refresh_from_db()
        assert self.organization.updated_at == before_updated_at

    def test_writes_zero_when_todays_usage_missing_and_report_is_zero(self) -> None:
        # Edge case: a freshly-billed resource arrives with no `todays_usage` key at
        # all, and ClickHouse reports 0 for the period. `existing.get("todays_usage")`
        # returns `None`, which compares unequal to `0`, so the patch must write `0`
        # explicitly — initializing the key on the row instead of leaving it absent.
        self.organization.usage = {
            "events": {"usage": 100, "limit": 1_000},  # no `todays_usage` key
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.save()

        changed = _patch_todays_usage(self.organization, _full_usage_counters(events=0))

        assert changed is True
        self.organization.refresh_from_db()
        assert self.organization.usage["events"]["todays_usage"] == 0
        # Sibling fields untouched.
        assert self.organization.usage["events"]["usage"] == 100
        assert self.organization.usage["events"]["limit"] == 1_000

    def test_partial_patch_writes_only_changed_resources(self) -> None:
        self.organization.usage = {
            "events": {"usage": 100, "limit": 1_000, "todays_usage": 5},
            "recordings": {"usage": 200, "limit": 1_000, "todays_usage": 5},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.save()
        before_updated_at = self.organization.updated_at

        # Only `events` changes; `recordings` stays identical.
        changed = _patch_todays_usage(self.organization, _full_usage_counters(events=42, recordings=5))

        assert changed is True
        # In-memory mirror reflects the change.
        assert self.organization.usage["events"]["todays_usage"] == 42
        assert self.organization.usage["recordings"]["todays_usage"] == 5

        self.organization.refresh_from_db()
        assert self.organization.usage["events"]["todays_usage"] == 42
        # Sibling fields untouched.
        assert self.organization.usage["events"]["usage"] == 100
        assert self.organization.usage["events"]["limit"] == 1_000
        assert self.organization.usage["recordings"]["todays_usage"] == 5
        assert self.organization.usage["period"] == ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"]
        # Matches prior `save(update_fields=["usage"])` behavior: `auto_now=True` only
        # fires for fields actually in `update_fields`, so `updated_at` wasn't bumped
        # before and isn't bumped now.
        assert self.organization.updated_at == before_updated_at

    def test_targeted_patch_does_not_clobber_concurrent_billing_write(self) -> None:
        self.organization.usage = {
            "events": {"usage": 100, "limit": 1_000, "todays_usage": 0},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.save()

        # Concurrent billing write lands fresh `usage` / `limit` / `period` after the
        # in-memory snapshot was loaded.
        Organization.objects.filter(id=self.organization.id).update(
            usage={
                "events": {"usage": 0, "limit": 50_000_000, "todays_usage": 0},
                "period": ["2021-02-01T00:00:00Z", "2021-02-28T23:59:59Z"],
            }
        )

        # The stale in-memory org still believes limit=1000; the targeted patch must
        # only touch `usage[events][todays_usage]` and leave billing-owned fields alone.
        changed = _patch_todays_usage(self.organization, _full_usage_counters(events=99))

        assert changed is True
        fresh = Organization.objects.get(id=self.organization.id)
        assert fresh.usage["events"]["todays_usage"] == 99
        assert fresh.usage["events"]["usage"] == 0
        assert fresh.usage["events"]["limit"] == 50_000_000
        assert fresh.usage["period"] == ["2021-02-01T00:00:00Z", "2021-02-28T23:59:59Z"]


@override_settings(CLOUD_DEPLOYMENT="US")
class TestUpdateOrganizationUsageFields(BaseTest):
    """Isolated unit coverage for the partial-write helper that writes the
    quota-limiting-owned keys (`quota_limited_until`, `quota_limiting_suspended_until`)
    inside `usage[resource]`."""

    def test_empty_fields_skips_db_write(self) -> None:
        self.organization.usage = {
            "events": {"usage": 100, "limit": 1_000, "todays_usage": 0},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.save()
        before_updated_at = self.organization.updated_at

        update_organization_usage_fields(self.organization, QuotaResource.EVENTS, {})

        self.organization.refresh_from_db()
        assert self.organization.updated_at == before_updated_at

    def test_set_and_delete_keys_in_one_call(self) -> None:
        self.organization.usage = {
            "events": {
                "usage": 100,
                "limit": 1_000,
                "todays_usage": 0,
                "quota_limiting_suspended_until": 1_700_000_000,
            },
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.save()

        update_organization_usage_fields(
            self.organization,
            QuotaResource.EVENTS,
            {"quota_limited_until": 1_800_000_000, "quota_limiting_suspended_until": None},
        )

        # In-memory mirror.
        assert self.organization.usage["events"]["quota_limited_until"] == 1_800_000_000
        assert "quota_limiting_suspended_until" not in self.organization.usage["events"]

        # Persisted state.
        self.organization.refresh_from_db()
        assert self.organization.usage["events"]["quota_limited_until"] == 1_800_000_000
        assert "quota_limiting_suspended_until" not in self.organization.usage["events"]
        # Billing-owned fields untouched.
        assert self.organization.usage["events"]["usage"] == 100
        assert self.organization.usage["events"]["limit"] == 1_000

    def test_all_none_deletes_on_missing_keys_is_a_noop(self) -> None:
        # Clearing markers that aren't present should not raise and should leave the
        # row's `usage` shape untouched (the SQL UPDATE still runs but produces an
        # equivalent jsonb). Mirrors the common cron path where `org_quota_limited_until`
        # clears markers on every "not over limit" pass even when there were none to
        # begin with.
        self.organization.usage = {
            "events": {"usage": 100, "limit": 1_000, "todays_usage": 0},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.save()
        before_usage = dict(self.organization.usage["events"])

        update_organization_usage_fields(
            self.organization,
            QuotaResource.EVENTS,
            {"quota_limited_until": None, "quota_limiting_suspended_until": None},
        )

        self.organization.refresh_from_db()
        # Same shape — no spurious null keys introduced, billing-owned fields untouched.
        assert self.organization.usage["events"] == before_usage

    def test_concurrent_billing_period_change_is_preserved(self) -> None:
        self.organization.usage = {
            "events": {"usage": 100, "limit": 1_000, "todays_usage": 0},
            "period": ["2021-01-01T00:00:00Z", "2021-01-31T23:59:59Z"],
        }
        self.organization.save()

        # Billing rewrites `usage` and `period` after we loaded our in-memory copy.
        Organization.objects.filter(id=self.organization.id).update(
            usage={
                "events": {"usage": 0, "limit": 10_000_000, "todays_usage": 0},
                "period": ["2021-02-01T00:00:00Z", "2021-02-28T23:59:59Z"],
            }
        )

        update_organization_usage_fields(
            self.organization, QuotaResource.EVENTS, {"quota_limited_until": 1_800_000_000}
        )

        fresh = Organization.objects.get(id=self.organization.id)
        assert fresh.usage["events"]["quota_limited_until"] == 1_800_000_000
        assert fresh.usage["events"]["usage"] == 0
        assert fresh.usage["events"]["limit"] == 10_000_000
        assert fresh.usage["period"] == ["2021-02-01T00:00:00Z", "2021-02-28T23:59:59Z"]
