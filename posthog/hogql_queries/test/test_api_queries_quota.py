from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQuery

from posthog.api_queries_quota import API_QUERIES_QUOTA_ERRORS_COUNTER, increment_api_queries_bytes
from posthog.exceptions import APIQueriesQuotaExceeded
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import (
    API_QUERIES_QUOTA_LIMITED_COUNTER,
    _api_queries_enforcement_enabled,
    _api_queries_quota_detail,
    _format_data_size,
    get_api_queries_quota_limited_until,
)


@override_settings(API_QUERIES_FREE_TIER_READ_BYTES_LIMIT=1000)
class TestGetApiQueriesQuotaLimitedUntil(BaseTest):
    def _set(self, has_active_subscription, counter_bytes):
        self.organization.has_active_subscription = has_active_subscription
        self.organization.save()
        if counter_bytes:
            increment_api_queries_bytes(str(self.organization.id), counter_bytes)

    @parameterized.expand(
        [
            # (has_active_subscription, counter_bytes, expect_limited)
            ("free_over_limit", False, 2000, True),
            ("free_under_limit", False, 500, False),
            ("paying_over_limit", True, 2000, False),
            ("unknown_subscription_over_limit", None, 2000, False),
        ]
    )
    def test_check_matrix(self, _name, has_active_subscription, counter_bytes, expect_limited):
        self._set(has_active_subscription, counter_bytes)
        result = get_api_queries_quota_limited_until(self.team)
        if expect_limited:
            assert result is not None and result.tzinfo is not None
        else:
            assert result is None

    @override_settings(API_QUERIES_FREE_TIER_READ_BYTES_LIMIT=0)
    def test_zero_setting_disables(self):
        self._set(False, 2000)
        assert get_api_queries_quota_limited_until(self.team) is None

    def test_counter_error_fails_open(self):
        self._set(False, 2000)
        with patch("posthog.hogql_queries.query_runner.get_api_queries_bytes", side_effect=Exception("redis down")):
            assert get_api_queries_quota_limited_until(self.team) is None

    def test_counter_error_increments_error_counter(self):
        self._set(False, 2000)
        before = API_QUERIES_QUOTA_ERRORS_COUNTER.labels(op="check")._value.get()
        with patch("posthog.hogql_queries.query_runner.get_api_queries_bytes", side_effect=Exception("redis down")):
            get_api_queries_quota_limited_until(self.team)
        after = API_QUERIES_QUOTA_ERRORS_COUNTER.labels(op="check")._value.get()
        assert after == before + 1


class TestApiQueriesQuotaDetail(SimpleTestCase):
    def test_detail_includes_usage_limit_and_reset(self):
        detail = _api_queries_quota_detail(
            used=62_500_000_000_000,
            limit=50_000_000_000_000,
            limited_until=datetime(2026, 9, 1, tzinfo=UTC),
            project_timezone="UTC",
        )
        assert "62.5 TB" in detail
        assert "50 TB" in detail
        assert "September 1, 2026 (UTC)" in detail
        assert "Billing settings" in detail

    def test_detail_renders_reset_in_project_timezone(self):
        detail = _api_queries_quota_detail(
            used=62_500_000_000_000,
            limit=50_000_000_000_000,
            limited_until=datetime(2026, 9, 1, tzinfo=UTC),
            project_timezone="America/Los_Angeles",
        )
        assert "August 31, 2026 at 17:00 (America/Los_Angeles)" in detail

    def test_detail_falls_back_to_utc_on_bad_timezone(self):
        detail = _api_queries_quota_detail(
            used=62_500_000_000_000,
            limit=50_000_000_000_000,
            limited_until=datetime(2026, 9, 1, tzinfo=UTC),
            project_timezone="Not/AZone",
        )
        assert "September 1, 2026 (UTC)" in detail

    @parameterized.expand(
        [
            ("terabytes_trimmed", 50_000_000_000_000, "50 TB"),
            ("terabytes_fraction", 62_500_000_000_000, "62.5 TB"),
            ("gigabytes", 500_000_000_000, "500 GB"),
            ("small_values_stay_bytes", 999, "999 bytes"),
        ]
    )
    def test_format_data_size(self, _name, bytes_count, expected):
        assert _format_data_size(bytes_count) == expected


class TestApiQueriesEnforcementEnabled(BaseTest):
    def test_flag_on_returns_true(self):
        with patch("posthog.hogql_queries.query_runner.posthoganalytics.feature_enabled", return_value=True):
            assert _api_queries_enforcement_enabled(self.team) is True

    def test_flag_service_error_fails_open_to_false(self):
        with patch(
            "posthog.hogql_queries.query_runner.posthoganalytics.feature_enabled",
            side_effect=Exception("flag service down"),
        ):
            assert _api_queries_enforcement_enabled(self.team) is False


class TestApiQueriesQuotaEnforcement(BaseTest):
    def _runner(self):
        runner = HogQLQueryRunner(query=HogQLQuery(query="select 1"), team=self.team)
        runner.is_query_service = True
        return runner

    def test_not_limited_is_noop(self):
        with patch("posthog.hogql_queries.query_runner.get_api_queries_quota_limited_until", return_value=None):
            self._runner()._enforce_api_queries_quota()  # must not raise

    def test_limited_flag_off_observes_and_runs(self):
        before = API_QUERIES_QUOTA_LIMITED_COUNTER.labels(surface="api", outcome="observed")._value.get()
        with (
            patch(
                "posthog.hogql_queries.query_runner.get_api_queries_quota_limited_until",
                return_value=datetime(2026, 9, 1, tzinfo=UTC),
            ),
            patch("posthog.hogql_queries.query_runner._api_queries_enforcement_enabled", return_value=False),
        ):
            self._runner()._enforce_api_queries_quota()  # must not raise
        after = API_QUERIES_QUOTA_LIMITED_COUNTER.labels(surface="api", outcome="observed")._value.get()
        assert after == before + 1

    def test_limited_flag_on_raises_402(self):
        before = API_QUERIES_QUOTA_LIMITED_COUNTER.labels(surface="api", outcome="enforced")._value.get()
        with (
            patch(
                "posthog.hogql_queries.query_runner.get_api_queries_quota_limited_until",
                return_value=datetime(2026, 9, 1, tzinfo=UTC),
            ),
            patch("posthog.hogql_queries.query_runner._api_queries_enforcement_enabled", return_value=True),
        ):
            with pytest.raises(APIQueriesQuotaExceeded) as exc_info:
                self._runner()._enforce_api_queries_quota()
        assert exc_info.value.status_code == 402
        after = API_QUERIES_QUOTA_LIMITED_COUNTER.labels(surface="api", outcome="enforced")._value.get()
        assert after == before + 1

    def test_flag_service_error_fails_open_to_observe(self):
        with (
            patch(
                "posthog.hogql_queries.query_runner.get_api_queries_quota_limited_until",
                return_value=datetime(2026, 9, 1, tzinfo=UTC),
            ),
            patch(
                "posthog.hogql_queries.query_runner.posthoganalytics.feature_enabled",
                side_effect=Exception("flag service down"),
            ),
        ):
            self._runner()._enforce_api_queries_quota()  # must not raise

    def test_call_with_rate_limits_enforces_quota_for_query_service(self):
        runner = self._runner()
        with (
            patch.object(runner, "calculate", return_value="stub result"),
            patch(
                "posthog.hogql_queries.query_runner.get_api_queries_quota_limited_until",
                return_value=datetime(2026, 9, 1, tzinfo=UTC),
            ),
            patch("posthog.hogql_queries.query_runner._api_queries_enforcement_enabled", return_value=True),
        ):
            with pytest.raises(APIQueriesQuotaExceeded):
                runner._call_with_rate_limits(dashboard_id=None)

    def test_call_with_rate_limits_skips_enforcement_for_non_query_service(self):
        runner = HogQLQueryRunner(query=HogQLQuery(query="select 1"), team=self.team)
        runner.is_query_service = False
        with (
            patch.object(runner, "calculate", return_value="stub result"),
            patch("posthog.hogql_queries.query_runner.get_api_queries_quota_limited_until") as check,
        ):
            result, _duration_ms = runner._call_with_rate_limits(dashboard_id=None)
        assert result == "stub result"
        check.assert_not_called()

    def test_concurrency_limit_no_longer_returns_zero_for_limited_teams(self):
        # get_api_queries_concurrency_limit reads the plain `posthog.settings` module
        # (not django.conf.settings), so @override_settings on the class doesn't reach it.
        runner = self._runner()
        with (
            patch("posthog.hogql_queries.query_runner.settings.API_QUERIES_ENABLED", True),
            patch("ee.billing.quota_limiting.list_limited_team_attributes", return_value=[self.team.api_token]),
        ):
            # Quota state (list_limited_team_attributes) must not affect the concurrency limit.
            assert runner.get_api_queries_concurrency_limit() != 0
