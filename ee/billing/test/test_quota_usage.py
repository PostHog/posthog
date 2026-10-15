import copy
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import DatabaseError, OperationalError, connection
from django.test import override_settings

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.redis import get_client
from posthog.usage_counters import UsageCounter, UsageCounterReport

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, update_all_orgs_billing_quotas
from ee.billing.quota_usage import QuotaUsageBatch


class TestQuotaUsageBatch(BaseTest):
    @parameterized.expand([("all_present", False), ("deleted_organization", True)])
    def test_multiple_patches_preserve_other_organizations_and_fields(self, _name, delete_second) -> None:
        other = Organization.objects.create(name="Other organization", slug="other-quota-organization")
        usage = {"events": {"usage": 10, "limit": 100, "todays_usage": 0}, "period": ["start", "end"]}
        Organization.objects.filter(id__in=[self.organization.id, other.id]).update(usage=usage)
        batch = QuotaUsageBatch()
        batch.patch(self.organization, [(["events", "todays_usage"], 20)])
        batch.patch(self.organization, [(["events", "quota_limited_until"], 1234)])
        batch.patch(other, [(["events", "todays_usage"], 30)])
        if delete_second:
            other.delete()

        batch.flush()

        self.organization.refresh_from_db()
        assert self.organization.usage == {
            **usage,
            "events": {"usage": 10, "limit": 100, "todays_usage": 20, "quota_limited_until": 1234},
        }
        if not delete_second:
            other.refresh_from_db()
            assert other.usage == {**usage, "events": {"usage": 10, "limit": 100, "todays_usage": 30}}

    @parameterized.expand(
        [("transient", OperationalError, 1), ("exhausted", OperationalError, 3), ("non_transient", DatabaseError, 1)]
    )
    @patch("posthoganalytics.capture")
    @patch("ee.billing.quota_usage.sleep")
    def test_failed_statement_rolls_back_batch_before_retry_or_events(
        self, _name, error_type, failures, _sleep, capture
    ) -> None:
        other = Organization.objects.create(name="Other organization", slug="other-quota-organization")
        usage = {"events": {"usage": 10, "limit": 100, "todays_usage": 0}}
        Organization.objects.filter(id__in=[self.organization.id, other.id]).update(usage=usage)
        batch = QuotaUsageBatch()
        batch.patch(self.organization, [(["events", "todays_usage"], 20)])
        batch.patch(other, [(["events", "todays_usage"], 30), (["events", "quota_limited_until"], 1234)])
        properties = {"usage": {"events": 20}}
        batch.report_action(self.organization, "organization quota limits changed", properties)
        properties["usage"]["events"] = 999
        writes = 0
        errors = 0

        def fail_second_statement(execute, sql, params, many, context):
            nonlocal writes, errors
            if sql.startswith("UPDATE posthog_organization AS o"):
                writes += 1
                if writes % 2 == 1:
                    assert Organization.objects.get(id=self.organization.id).usage == usage
                    assert Organization.objects.get(id=other.id).usage == usage
                elif errors < failures:
                    errors += 1
                    raise error_type("synthetic write failure")
            return execute(sql, params, many, context)

        succeeds = error_type is OperationalError and failures == 1
        with connection.execute_wrapper(fail_second_statement), self.captureOnCommitCallbacks(execute=True):
            if succeeds:
                batch.flush()
            else:
                with self.assertRaises(error_type):
                    batch.flush()
            capture.assert_not_called()

        self.organization.refresh_from_db()
        other.refresh_from_db()
        if succeeds:
            assert self.organization.usage is not None
            assert self.organization.usage["events"]["todays_usage"] == 20
            assert other.usage["events"]["todays_usage"] == 30
            assert other.usage["events"]["quota_limited_until"] == 1234
            capture.assert_called_once()
            assert capture.call_args.kwargs["properties"] == {"usage": {"events": 20}}
        else:
            assert self.organization.usage == other.usage == usage
            capture.assert_not_called()


@override_settings(CLOUD_DEPLOYMENT="US")
@time_machine.travel("2026-06-15T12:00:00Z", tick=False)
class TestBatchedQuotaRun(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("ee.billing.quota_limiting.QUOTA_ORGANIZATION_BATCH_SIZE", 2))
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=False))
        self.capture = self.enterContext(patch("posthoganalytics.capture"))
        self.enterContext(patch("ee.billing.quota_usage.sleep"))
        self.redis = get_client()
        self.redis.delete(
            *[cache.value + resource.value for cache in QuotaLimitingCaches for resource in QuotaResource]
        )
        others = [
            Organization.objects.create(name=f"Quota organization {i}", slug=f"quota-organization-{i}")
            for i in range(2)
        ]
        for org in others:
            Team.objects.create(organization=org)
        self.orgs = sorted([self.organization, *others], key=lambda org: org.id)
        self.teams = {str(org.id): list(org.teams.all()) for org in self.orgs}
        self.teams[str(self.orgs[0].id)].append(Team.objects.create(organization=self.orgs[0]))
        self.usage: dict[str, Any] = {
            "events": {"usage": 0, "limit": 100, "todays_usage": 0},
            "period": ["2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"],
        }
        Organization.objects.filter(id__in=[org.id for org in self.orgs]).update(
            usage=self.usage, customer_trust_scores={}
        )
        counts: dict[str, list[tuple[int, int]]] = {counter.value: [] for counter in UsageCounter}
        counts[UsageCounter.EVENTS.value] = [
            (team.id, 60 if index == 0 else 200)
            for index, org in enumerate(self.orgs)
            for team in self.teams[str(org.id)]
        ]
        counts["teams_with_sandbox_compute_cpu_millicore_seconds_in_period"] = []
        counts["teams_with_sandbox_compute_memory_mib_seconds_in_period"] = []
        self.enterContext(
            patch(
                "posthog.usage_counters.UsageCounterService.fetch_report",
                return_value=UsageCounterReport(counts=counts),
            )
        )
        self.enterContext(
            patch("ee.billing.quota_limiting.get_teams_with_api_queries_metrics", return_value={"read_bytes": []})
        )
        self.capture.reset_mock()

    def test_orgs_and_all_their_teams_are_processed_across_chunks(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            result = update_all_orgs_billing_quotas()

        assert set(result.quota_limited_orgs["events"]) == {str(org.id) for org in self.orgs}
        assert result.stats["orgs_processed"] == result.stats["orgs_total"] == 3
        assert result.stats["orgs_limited"] == 3
        for index, org in enumerate(self.orgs):
            org.refresh_from_db()
            assert org.usage["events"]["todays_usage"] == (120 if index == 0 else 200)
            for team in self.teams[str(org.id)]:
                assert (
                    self.redis.zscore("@posthog/quota-limits/events", team.api_token)
                    == result.quota_limited_orgs["events"][str(org.id)]
                )

    def test_exhausted_later_batch_leaves_redis_unchanged_and_next_run_recovers(self) -> None:
        old_team = self.teams[str(self.orgs[0].id)][0]
        self.redis.zadd("@posthog/quota-limits/events", {old_team.api_token: 1_782_864_000})
        initial_redis = self.redis.zrange("@posthog/quota-limits/events", 0, -1, withscores=True)
        failed_id = self.orgs[-1].id

        def fail_last_batch(execute, sql, params, many, context):
            if sql.startswith("UPDATE posthog_organization AS o") and failed_id in params:
                raise OperationalError("synthetic connection failure")
            return execute(sql, params, many, context)

        with connection.execute_wrapper(fail_last_batch), self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(OperationalError):
                update_all_orgs_billing_quotas()
        assert self.redis.zrange("@posthog/quota-limits/events", 0, -1, withscores=True) == initial_redis
        self.orgs[-1].refresh_from_db()
        assert self.orgs[-1].usage == self.usage
        assert not any(call.kwargs["distinct_id"] == str(failed_id) for call in self.capture.call_args_list)

        result = update_all_orgs_billing_quotas()
        assert len(result.quota_limited_orgs["events"]) == 3
        self.orgs[-1].refresh_from_db()
        assert self.orgs[-1].usage["events"]["todays_usage"] == 200
        assert self.redis.zcard("@posthog/quota-limits/events") == 4

    def test_failed_decision_preserves_previous_limits_and_discards_partial_updates(self) -> None:
        failed_org = self.orgs[0]
        usage = copy.deepcopy(self.usage)
        usage["signals_credits"] = {"usage": 4500, "limit": 4500, "todays_usage": 0}
        Organization.objects.filter(id=failed_org.id).update(usage=usage)
        for team in self.teams[str(failed_org.id)]:
            self.redis.zadd("@posthog/quota-limits/events", {team.api_token: 1_782_864_000})
            self.redis.zadd("@posthog/quota-limiting-suspended/signals_credits", {team.api_token: 1_782_864_000})
        with (
            patch("ee.billing.quota_limiting.get_self_driving_credits_used_in_period_for_org", return_value=0),
            patch(
                "ee.billing.quota_limiting.get_signals_credited_refund_credits_for_org",
                side_effect=DatabaseError("synthetic query failure"),
            ),
            patch("ee.billing.quota_limiting.capture_exception"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = update_all_orgs_billing_quotas()

        failed_org.refresh_from_db()
        assert failed_org.usage == usage
        assert str(failed_org.id) not in result.quota_limited_orgs["events"]
        assert len(result.quota_limited_orgs["events"]) == 2
        for team in self.teams[str(failed_org.id)]:
            assert self.redis.zscore("@posthog/quota-limits/events", team.api_token) == 1_782_864_000
            assert (
                self.redis.zscore("@posthog/quota-limiting-suspended/signals_credits", team.api_token) == 1_782_864_000
            )
        assert not any(call.kwargs["distinct_id"] == str(failed_org.id) for call in self.capture.call_args_list)
