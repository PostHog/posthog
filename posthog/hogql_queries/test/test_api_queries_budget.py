import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import HogQLQuery

from posthog.api_queries_budget import budget_spec_for, debit, refill_and_read
from posthog.exceptions import APIQueriesBudgetExceeded
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import (
    API_QUERIES_BUDGET_BALANCE_HISTOGRAM,
    API_QUERIES_BUDGET_LIMITED_COUNTER,
    get_api_queries_budget_status,
)


@override_settings(API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR=3600, API_QUERIES_BUDGET_CAPACITY_HOURS=1)
class TestApiQueriesBudgetEnforcement(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization.has_active_subscription = False
        self.organization.save()

    def _runner(self, is_query_service: bool = True) -> HogQLQueryRunner:
        runner = HogQLQueryRunner(query=HogQLQuery(query="SELECT 1"), team=self.team)
        runner.is_query_service = is_query_service
        return runner

    def _drain(self) -> None:
        refill_and_read(str(self.team.pk), budget_spec_for(self.organization))
        debit(str(self.team.pk), 10_000)

    def test_status_reports_remaining_and_retry_after(self):
        self._drain()
        status = get_api_queries_budget_status(self.team)
        assert status is not None
        assert status.remaining_bytes < 0
        assert status.retry_after_seconds > 0

    @override_settings(API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR=0)
    def test_disabled_budget_has_no_status(self):
        assert get_api_queries_budget_status(self.team) is None

    def test_redis_error_admits(self):
        with patch("posthog.hogql_queries.query_runner.refill_and_read", return_value=None):
            assert get_api_queries_budget_status(self.team) is None

    @parameterized.expand([("observed", False), ("enforced", True)])
    def test_over_budget_is_counted_and_only_refused_when_enforced(self, outcome, enforced):
        self._drain()
        before = API_QUERIES_BUDGET_LIMITED_COUNTER.labels(outcome=outcome)._value.get()
        with patch("posthog.hogql_queries.query_runner._api_queries_budget_enforcement_enabled", return_value=enforced):
            if enforced:
                with pytest.raises(APIQueriesBudgetExceeded) as excinfo:
                    self._runner()._enforce_api_queries_budget()
                assert excinfo.value.status_code == 429
                assert (excinfo.value.wait or 0) > 0
            else:
                self._runner()._enforce_api_queries_budget()
        assert API_QUERIES_BUDGET_LIMITED_COUNTER.labels(outcome=outcome)._value.get() == before + 1

    def test_under_budget_admits_without_touching_the_counter_even_when_enforced(self):
        refill_and_read(str(self.team.pk), budget_spec_for(self.organization))
        before = API_QUERIES_BUDGET_LIMITED_COUNTER.labels(outcome="enforced")._value.get()
        checks_before = sum(bucket.get() for bucket in API_QUERIES_BUDGET_BALANCE_HISTOGRAM._buckets)
        with patch("posthog.hogql_queries.query_runner._api_queries_budget_enforcement_enabled", return_value=True):
            self._runner()._enforce_api_queries_budget()
        assert API_QUERIES_BUDGET_LIMITED_COUNTER.labels(outcome="enforced")._value.get() == before
        assert sum(bucket.get() for bucket in API_QUERIES_BUDGET_BALANCE_HISTOGRAM._buckets) == checks_before + 1

    def test_flag_service_error_fails_open_to_observe(self):
        self._drain()
        with patch(
            "posthog.hogql_queries.query_runner.posthoganalytics.feature_enabled",
            side_effect=Exception("flag service down"),
        ):
            self._runner()._enforce_api_queries_budget()

    @parameterized.expand([("api_key_query_refused", True), ("app_query_admitted", False)])
    def test_call_with_rate_limits_enforces_the_budget_for_api_key_queries_only(self, _name, is_query_service):
        self._drain()
        runner = self._runner(is_query_service=is_query_service)
        with (
            patch("posthog.hogql_queries.query_runner._api_queries_budget_enforcement_enabled", return_value=True),
            patch.object(runner, "calculate", return_value="stub result"),
        ):
            if is_query_service:
                with pytest.raises(APIQueriesBudgetExceeded):
                    runner._call_with_rate_limits(dashboard_id=None)
            else:
                result, _duration_ms = runner._call_with_rate_limits(dashboard_id=None)
                assert result == "stub result"

    def test_concurrency_limit_ignores_billing_quota_limited_teams(self):
        # get_api_queries_concurrency_limit reads the plain `posthog.settings` module
        # (not django.conf.settings), so @override_settings on the class doesn't reach it.
        runner = self._runner()
        with (
            patch("posthog.hogql_queries.query_runner.settings.API_QUERIES_ENABLED", True),
            patch("ee.billing.quota_limiting.list_limited_team_attributes", return_value=[self.team.api_token]),
        ):
            assert runner.get_api_queries_concurrency_limit() != 0
