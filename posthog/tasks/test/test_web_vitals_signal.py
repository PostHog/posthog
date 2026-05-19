from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.tasks.web_vitals_signal import (
    WEB_VITALS_SIGNAL_DEDUP_TTL_SECONDS,
    WEB_VITALS_SIGNAL_REGRESSION_CONSECUTIVE_REQUIRED,
    WEB_VITALS_SIGNAL_SOURCE_PRODUCT,
    WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION,
    WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING,
    WEB_VITALS_THRESHOLDS,
    WebVitalsRegressionSignal,
    WebVitalsThresholdCrossingSignal,
    _daily_count_key,
    _dedup_key,
    _enabled_cache_key,
    classify_band,
    enqueue_web_vitals_signals,
    get_last_band,
    increment_regression_streak,
    reset_regression_streak,
    set_last_band,
)


def _threshold_signal(**overrides: Any) -> WebVitalsThresholdCrossingSignal:
    defaults: dict[str, Any] = {
        "metric": "LCP",
        "route": "/checkout",
        "device_class": "Mobile",
        "p75_value": 4350.0,
        "threshold_band": "poor",
        "previous_band": "needs_improvements",
        "sample_count": 3421,
        "window_hours": 24,
    }
    defaults.update(overrides)
    return WebVitalsThresholdCrossingSignal(**defaults)


def _regression_signal(**overrides: Any) -> WebVitalsRegressionSignal:
    defaults: dict[str, Any] = {
        "metric": "INP",
        "route": "/dashboard",
        "device_class": "Desktop",
        "current_p75": 340.0,
        "baseline_p75": 180.0,
        "sample_count": 421,
        "baseline_sample_count": 4210,
        "window_hours": 2,
        "baseline_window_days": 7,
    }
    defaults.update(overrides)
    return WebVitalsRegressionSignal(**defaults)


class TestWebVitalsClassifyBand(BaseTest):
    @parameterized.expand(
        [
            ("LCP_good_below", "LCP", 2000.0, "good"),
            ("LCP_good_edge", "LCP", 2500.0, "good"),
            ("LCP_needs_improvements", "LCP", 3500.0, "needs_improvements"),
            ("LCP_needs_improvements_edge", "LCP", 4000.0, "needs_improvements"),
            ("LCP_poor", "LCP", 4500.0, "poor"),
            ("INP_good", "INP", 150.0, "good"),
            ("INP_needs", "INP", 350.0, "needs_improvements"),
            ("INP_poor", "INP", 700.0, "poor"),
            ("CLS_good", "CLS", 0.05, "good"),
            ("CLS_needs", "CLS", 0.2, "needs_improvements"),
            ("CLS_poor", "CLS", 0.3, "poor"),
            ("FCP_good", "FCP", 1500.0, "good"),
            ("FCP_needs", "FCP", 2500.0, "needs_improvements"),
            ("FCP_poor", "FCP", 4000.0, "poor"),
        ]
    )
    def test_classification_matches_google_thresholds(
        self, _name: str, metric: str, value: float, expected: str
    ) -> None:
        assert classify_band(metric, value) == expected


class TestThresholdCrossingFingerprint(BaseTest):
    @parameterized.expand(
        [
            ("identity_same", _threshold_signal(), _threshold_signal(), True),
            (
                "metric_differs",
                _threshold_signal(),
                _threshold_signal(metric="INP"),
                False,
            ),
            (
                "route_differs",
                _threshold_signal(),
                _threshold_signal(route="/home"),
                False,
            ),
            (
                "device_class_differs",
                _threshold_signal(),
                _threshold_signal(device_class="Desktop"),
                False,
            ),
            (
                "band_differs",
                _threshold_signal(),
                _threshold_signal(threshold_band="needs_improvements"),
                False,
            ),
            (
                "previous_band_differs",
                _threshold_signal(previous_band="good"),
                _threshold_signal(previous_band="needs_improvements"),
                False,
            ),
            (
                "value_changes_dont_affect_fingerprint",
                _threshold_signal(p75_value=4100.0, sample_count=200),
                _threshold_signal(p75_value=8000.0, sample_count=99999),
                True,
            ),
        ]
    )
    def test_fingerprint_identity(
        self,
        _name: str,
        a: WebVitalsThresholdCrossingSignal,
        b: WebVitalsThresholdCrossingSignal,
        should_match: bool,
    ) -> None:
        assert (a.fingerprint() == b.fingerprint()) is should_match


class TestThresholdCrossingDescription(BaseTest):
    @parameterized.expand(["LCP", "INP", "CLS", "FCP"])
    def test_description_mentions_metric_and_route(self, metric: str) -> None:
        signal = _threshold_signal(metric=metric, route="/checkout")
        description = signal.description()
        assert metric in description
        assert "/checkout" in description
        assert "## What happened" in description
        assert "## Common causes" in description
        assert "## Triage" in description

    def test_description_includes_sample_count(self) -> None:
        description = _threshold_signal(sample_count=3421).description()
        assert "3,421" in description

    def test_description_includes_previous_band_when_present(self) -> None:
        description = _threshold_signal(previous_band="needs_improvements").description()
        assert "needs improvement" in description.lower()

    def test_description_handles_no_previous_band(self) -> None:
        description = _threshold_signal(previous_band=None).description()
        assert "Previous band" not in description

    def test_extra_payload_includes_thresholds(self) -> None:
        extra = _threshold_signal(metric="LCP").signal_extra()
        good, poor = WEB_VITALS_THRESHOLDS["LCP"]
        assert extra["good_threshold"] == good
        assert extra["poor_threshold"] == poor
        assert extra["metric"] == "LCP"
        assert extra["threshold_band"] == "poor"


class TestRegressionSignal(BaseTest):
    def test_pct_change_calculation(self) -> None:
        signal = _regression_signal(current_p75=340.0, baseline_p75=180.0)
        assert abs(signal.pct_change - ((340 - 180) / 180 * 100)) < 0.01

    def test_pct_change_zero_baseline_safe(self) -> None:
        signal = _regression_signal(baseline_p75=0.0)
        assert signal.pct_change == 0.0

    def test_fingerprint_excludes_value(self) -> None:
        a = _regression_signal(current_p75=300.0)
        b = _regression_signal(current_p75=900.0)
        assert a.fingerprint() == b.fingerprint()

    @parameterized.expand(
        [
            ("metric", {"metric": "LCP"}),
            ("route", {"route": "/other"}),
            ("device_class", {"device_class": "Mobile"}),
        ]
    )
    def test_fingerprint_distinguishes_by_identity(self, _name: str, override: dict[str, Any]) -> None:
        base = _regression_signal()
        other = _regression_signal(**override)
        assert base.fingerprint() != other.fingerprint()

    def test_description_includes_baseline_and_current(self) -> None:
        description = _regression_signal(current_p75=340.0, baseline_p75=180.0).description()
        assert "340" in description
        assert "180" in description
        assert "%" in description


def _enable_signal(team_id: int, source_type: str) -> None:
    cache.set(_enabled_cache_key(team_id, source_type), True, 60)


def _disable_signal(team_id: int, source_type: str) -> None:
    cache.set(_enabled_cache_key(team_id, source_type), False, 60)


class _GateTestBase(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        from posthog.redis import get_client

        client = get_client()
        for pattern in (
            "web_vitals_signal_dedup:*",
            "web_vitals_signal_daily_count:*",
            "web_vitals_signal_band:*",
            "web_vitals_signal_streak:*",
        ):
            for key in client.scan_iter(match=pattern):
                client.delete(key)
        for source_type in (
            WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING,
            WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION,
        ):
            cache.delete(_enabled_cache_key(self.team.id, source_type))
            _enable_signal(self.team.id, source_type)


class TestWebVitalsSignalGates(_GateTestBase):
    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_first_emits(self, mock_emit: AsyncMock) -> None:
        result = enqueue_web_vitals_signals(self.team.id, [_threshold_signal()])
        assert result == 1
        assert mock_emit.await_count == 1
        kwargs = mock_emit.await_args.kwargs
        assert kwargs["source_product"] == WEB_VITALS_SIGNAL_SOURCE_PRODUCT
        assert kwargs["source_type"] == WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING

    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_duplicate_drops(self, mock_emit: AsyncMock) -> None:
        first = enqueue_web_vitals_signals(self.team.id, [_threshold_signal()])
        second = enqueue_web_vitals_signals(self.team.id, [_threshold_signal()])
        assert first == 1
        assert second == 0
        assert mock_emit.await_count == 1

    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_distinct_batch_all_emit(self, mock_emit: AsyncMock) -> None:
        signals = [
            _threshold_signal(metric="LCP"),
            _threshold_signal(metric="INP"),
            _threshold_signal(metric="CLS"),
        ]
        result = enqueue_web_vitals_signals(self.team.id, signals)
        assert result == 3
        assert mock_emit.await_count == 3

    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_mixed_batch_emits_both_types(self, mock_emit: AsyncMock) -> None:
        signals = [_threshold_signal(), _regression_signal()]
        result = enqueue_web_vitals_signals(self.team.id, signals)
        assert result == 2
        source_types = {call.kwargs["source_type"] for call in mock_emit.await_args_list}
        assert source_types == {
            WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING,
            WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION,
        }

    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_disabled_source_drops_only_that_type(self, mock_emit: AsyncMock) -> None:
        _disable_signal(self.team.id, WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION)
        signals = [_threshold_signal(), _regression_signal()]
        result = enqueue_web_vitals_signals(self.team.id, signals)
        assert result == 1
        assert mock_emit.await_count == 1
        assert mock_emit.await_args.kwargs["source_type"] == WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING

    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_ops_kill_switch_drops_everything(self, mock_emit: AsyncMock) -> None:
        with self.settings(WEB_VITALS_SIGNAL_EMISSION_ENABLED=False):
            result = enqueue_web_vitals_signals(self.team.id, [_threshold_signal()])
        assert result == 0
        mock_emit.assert_not_awaited()

    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_isolated_per_team(self, mock_emit: AsyncMock) -> None:
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        for source_type in (
            WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING,
            WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION,
        ):
            _enable_signal(other_team.id, source_type)

        enqueue_web_vitals_signals(self.team.id, [_threshold_signal()])
        enqueue_web_vitals_signals(other_team.id, [_threshold_signal()])
        assert mock_emit.await_count == 2

    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_dedup_ttl_is_24_hours(self, mock_emit: AsyncMock) -> None:
        from posthog.redis import get_client

        signal = _threshold_signal()
        enqueue_web_vitals_signals(self.team.id, [signal])

        key = _dedup_key(self.team.id, WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING, signal.fingerprint())
        ttl = get_client().ttl(key)
        assert 0 < ttl <= WEB_VITALS_SIGNAL_DEDUP_TTL_SECONDS
        assert mock_emit.await_count == 1

    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_daily_cap_drops_excess(self, mock_emit: AsyncMock) -> None:
        with self.settings(WEB_VITALS_SIGNAL_DAILY_CAP_PER_TEAM=2):
            signals = [
                _threshold_signal(metric="LCP"),
                _threshold_signal(metric="INP"),
                _threshold_signal(metric="CLS"),
            ]
            result = enqueue_web_vitals_signals(self.team.id, signals)
        assert result == 2
        assert mock_emit.await_count == 2

    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_daily_cap_zero_drops_everything(self, mock_emit: AsyncMock) -> None:
        with self.settings(WEB_VITALS_SIGNAL_DAILY_CAP_PER_TEAM=0):
            result = enqueue_web_vitals_signals(self.team.id, [_threshold_signal()])
        assert result == 0
        mock_emit.assert_not_awaited()

    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    @patch("posthog.tasks.web_vitals_signal.get_client")
    def test_redis_count_error_drops(self, mock_get_client: MagicMock, mock_emit: AsyncMock) -> None:
        fake_client = mock_get_client.return_value
        fake_client.incrby.side_effect = RuntimeError("redis down")
        result = enqueue_web_vitals_signals(self.team.id, [_threshold_signal()])
        assert result == 0
        mock_emit.assert_not_awaited()

    @patch(
        "posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock, side_effect=RuntimeError("buffer down")
    )
    def test_emit_failure_releases_dedup_key(self, _mock_emit: AsyncMock) -> None:
        from posthog.redis import get_client

        signal = _threshold_signal()
        result = enqueue_web_vitals_signals(self.team.id, [signal])
        assert result == 0

        key = _dedup_key(self.team.id, WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING, signal.fingerprint())
        client = get_client()
        assert client.get(key) is None
        count = client.get(_daily_count_key(self.team.id))
        assert count is None or int(count) == 0

    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_missing_team_drops_all(self, mock_emit: AsyncMock) -> None:
        nonexistent_team_id = 999999
        _enable_signal(nonexistent_team_id, WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING)
        result = enqueue_web_vitals_signals(nonexistent_team_id, [_threshold_signal()])
        assert result == 0
        mock_emit.assert_not_awaited()

    @patch("posthog.tasks.web_vitals_signal.SignalSourceConfig.is_source_enabled")
    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_opt_in_check_is_cached(self, mock_emit: AsyncMock, mock_is_enabled: MagicMock) -> None:
        cache.delete(_enabled_cache_key(self.team.id, WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING))
        mock_is_enabled.return_value = True

        enqueue_web_vitals_signals(self.team.id, [_threshold_signal(metric="LCP")])
        enqueue_web_vitals_signals(self.team.id, [_threshold_signal(metric="INP")])
        enqueue_web_vitals_signals(self.team.id, [_threshold_signal(metric="CLS")])
        # One DB hit per source_type (only THRESHOLD_CROSSING used here).
        assert mock_is_enabled.call_count == 1
        assert mock_emit.await_count == 3


class TestWebVitalsBandState(_GateTestBase):
    def test_band_state_roundtrip(self) -> None:
        assert get_last_band(self.team.id, "LCP", "/x", "Mobile") is None
        set_last_band(self.team.id, "LCP", "/x", "Mobile", "needs_improvements")
        assert get_last_band(self.team.id, "LCP", "/x", "Mobile") == "needs_improvements"

    def test_band_state_per_route_device_metric(self) -> None:
        set_last_band(self.team.id, "LCP", "/x", "Mobile", "poor")
        assert get_last_band(self.team.id, "LCP", "/x", "Mobile") == "poor"
        assert get_last_band(self.team.id, "LCP", "/x", "Desktop") is None
        assert get_last_band(self.team.id, "LCP", "/y", "Mobile") is None
        assert get_last_band(self.team.id, "INP", "/x", "Mobile") is None


class TestWebVitalsRegressionStreak(_GateTestBase):
    def test_streak_increments_until_threshold_then_resets(self) -> None:
        first = increment_regression_streak(self.team.id, "INP", "/x", "Desktop")
        second = increment_regression_streak(self.team.id, "INP", "/x", "Desktop")
        assert first == 1
        assert second == 2
        assert second >= WEB_VITALS_SIGNAL_REGRESSION_CONSECUTIVE_REQUIRED

        reset_regression_streak(self.team.id, "INP", "/x", "Desktop")
        assert increment_regression_streak(self.team.id, "INP", "/x", "Desktop") == 1

    def test_streak_isolated_per_identity(self) -> None:
        increment_regression_streak(self.team.id, "INP", "/x", "Desktop")
        increment_regression_streak(self.team.id, "INP", "/x", "Desktop")
        # Different identity → starts fresh
        assert increment_regression_streak(self.team.id, "INP", "/y", "Desktop") == 1
        assert increment_regression_streak(self.team.id, "INP", "/x", "Mobile") == 1
        assert increment_regression_streak(self.team.id, "LCP", "/x", "Desktop") == 1
