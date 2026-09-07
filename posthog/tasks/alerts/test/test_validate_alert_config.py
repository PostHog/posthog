from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from parameterized import parameterized

from products.alerts.backend.evaluation.validation import validate_alert_config


def _base_condition(type: str = "absolute_value") -> dict[str, Any]:
    return {"type": type}


def _base_config(series_index: int = 0) -> dict[str, Any]:
    return {"type": "TrendsAlertConfig", "series_index": series_index}


def _base_query(series_count: int = 1, display: str | None = None) -> dict[str, Any]:
    query: dict[str, Any] = {
        "kind": "TrendsQuery",
        "series": [{"kind": "EventsNode", "event": f"$event_{i}"} for i in range(series_count)],
    }
    if display:
        query["trendsFilter"] = {"display": display}
    return query


def _hogql_config() -> dict[str, Any]:
    return {"type": "HogQLAlertConfig", "evaluation": "last_row"}


def _hogql_query() -> dict[str, Any]:
    return {"kind": "HogQLQuery", "query": "SELECT count() FROM events"}


def _funnels_config(metric: str = "conversion_from_start") -> dict[str, Any]:
    return {"type": "FunnelsAlertConfig", "metric": metric, "funnel_step": None}


def _funnels_query() -> dict[str, Any]:
    return {
        "kind": "FunnelsQuery",
        "series": [{"kind": "EventsNode", "event": "a"}, {"kind": "EventsNode", "event": "b"}],
    }


def _base_threshold(type: str = "absolute", bounds: dict[str, Any] | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {"type": type}
    if bounds is None:
        bounds = {"upper": 1.0}
    config["bounds"] = bounds
    return config


class TestValidateAlertConfig:
    @parameterized.expand(
        [
            (
                "valid_absolute_config",
                _base_query(),
                _base_condition(),
                _base_config(),
                _base_threshold(),
                "daily",
                None,
            ),
            (
                "valid_relative_increase",
                _base_query(display="ActionsLineGraph"),
                _base_condition("relative_increase"),
                _base_config(),
                _base_threshold(),
                "daily",
                None,
            ),
            (
                "none_condition",
                _base_query(),
                None,
                _base_config(),
                None,
                "daily",
                "Alert has invalid condition: None",
            ),
            (
                "empty_condition",
                _base_query(),
                {},
                _base_config(),
                None,
                "daily",
                "Alert has invalid condition",
            ),
            (
                "invalid_condition_type",
                _base_query(),
                {"type": "bogus"},
                _base_config(),
                None,
                "daily",
                "Alert has invalid condition",
            ),
            (
                "missing_config",
                _base_query(),
                _base_condition(),
                None,
                None,
                "daily",
                "Unsupported alert config type: None",
            ),
            (
                "missing_config_type",
                _base_query(),
                _base_condition(),
                {"series_index": 0},
                None,
                "daily",
                "Unsupported alert config type",
            ),
            (
                "invalid_config_schema",
                _base_query(),
                _base_condition(),
                {"type": "TrendsAlertConfig"},
                None,
                "daily",
                "Alert has invalid TrendsAlertConfig",
            ),
            (
                "unsupported_query_kind",
                {"kind": "FunnelsQuery", "series": []},
                _base_condition(),
                _base_config(),
                None,
                "daily",
                "query kind 'FunnelsQuery' is not supported",
            ),
            (
                "wrapper_node_unwrapped",
                {"kind": "InsightVizNode", "source": _base_query()},
                _base_condition(),
                _base_config(),
                _base_threshold(),
                "daily",
                None,
            ),
            (
                "relative_on_pie",
                _base_query(display="ActionsPie"),
                _base_condition("relative_increase"),
                _base_config(),
                None,
                "daily",
                "not compatible with non time series",
            ),
            (
                "relative_on_bold_number",
                _base_query(display="BoldNumber"),
                _base_condition("relative_decrease"),
                _base_config(),
                None,
                "daily",
                "not compatible with non time series",
            ),
            (
                "absolute_with_percentage_threshold",
                _base_query(),
                _base_condition("absolute_value"),
                _base_config(),
                _base_threshold("percentage"),
                "daily",
                "Absolute value alerts require an absolute threshold, but a percentage threshold was configured",
            ),
            (
                "check_ongoing_no_upper_absolute",
                _base_query(),
                _base_condition("absolute_value"),
                {"type": "TrendsAlertConfig", "series_index": 0, "check_ongoing_interval": True},
                _base_threshold("absolute", {"lower": 0}),
                "daily",
                "check_ongoing_interval is only supported .* when upper threshold is specified",
            ),
            (
                "check_ongoing_no_upper_relative",
                _base_query(display="ActionsLineGraph"),
                _base_condition("relative_increase"),
                {"type": "TrendsAlertConfig", "series_index": 0, "check_ongoing_interval": True},
                _base_threshold("absolute", {"lower": 0}),
                "daily",
                "check_ongoing_interval is only supported .* when upper threshold is specified",
            ),
            (
                "series_index_out_of_range",
                _base_query(series_count=1),
                _base_condition(),
                _base_config(series_index=5),
                None,
                "daily",
                r"series_index 5 is out of range \(query has 1 series\)",
            ),
            (
                "series_index_valid_with_formulas",
                {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    "trendsFilter": {
                        "display": "BoldNumber",
                        "formulaNodes": [
                            {"formula": "A"},
                            {"formula": "A*2"},
                        ],
                    },
                },
                _base_condition(),
                _base_config(series_index=1),
                _base_threshold(),
                "daily",
                None,
            ),
            (
                "series_index_out_of_range_with_formulas",
                {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    "trendsFilter": {
                        "display": "BoldNumber",
                        "formulaNodes": [
                            {"formula": "A"},
                            {"formula": "A*2"},
                        ],
                    },
                },
                _base_condition(),
                _base_config(series_index=2),
                None,
                "daily",
                r"series_index 2 is out of range \(query has 2 series\)",
            ),
            (
                "valid_calculation_interval",
                _base_query(),
                _base_condition(),
                _base_config(),
                _base_threshold(),
                "daily",
                None,
            ),
            (
                "invalid_calculation_interval",
                _base_query(),
                _base_condition(),
                _base_config(),
                _base_threshold(),
                "every_5_minutes",
                "Invalid calculation interval: every_5_minutes",
            ),
            (
                "none_calculation_interval",
                _base_query(),
                _base_condition(),
                _base_config(),
                _base_threshold(),
                None,
                "Invalid calculation interval: None",
            ),
            (
                "valid_hogql_config",
                _hogql_query(),
                _base_condition(),
                _hogql_config(),
                _base_threshold(),
                "daily",
                None,
            ),
            (
                "hogql_config_with_trends_query_rejected",
                _base_query(),
                _base_condition(),
                _hogql_config(),
                _base_threshold(),
                "daily",
                "SQL alert config requires a HogQLQuery insight",
            ),
            (
                "hogql_absolute_condition_with_percentage_threshold_rejected",
                _hogql_query(),
                _base_condition("absolute_value"),
                _hogql_config(),
                _base_threshold(type="percentage"),
                "daily",
                "Absolute value alerts require an absolute threshold",
            ),
            (
                "valid_funnels_config",
                _funnels_query(),
                _base_condition("absolute_value"),
                _funnels_config(),
                _base_threshold(),
                "daily",
                None,
            ),
            (
                "funnels_config_with_trends_query_rejected",
                _base_query(),
                _base_condition("absolute_value"),
                _funnels_config(),
                _base_threshold(),
                "daily",
                "Funnel alert config requires a FunnelsQuery insight",
            ),
            (
                "funnels_relative_decrease_rejected",
                _funnels_query(),
                _base_condition("relative_decrease"),
                _funnels_config(),
                _base_threshold(),
                "daily",
                "This funnel only supports absolute value conditions",
            ),
            (
                "funnels_relative_increase_rejected",
                _funnels_query(),
                _base_condition("relative_increase"),
                _funnels_config(),
                _base_threshold(),
                "daily",
                "This funnel only supports absolute value conditions",
            ),
            (
                "funnels_from_previous_at_step_zero_rejected",
                _funnels_query(),
                _base_condition("absolute_value"),
                {"type": "FunnelsAlertConfig", "metric": "conversion_from_previous", "funnel_step": 0},
                _base_threshold(),
                "daily",
                "undefined at the first step",
            ),
            (
                "funnels_negative_step_rejected",
                _funnels_query(),
                _base_condition("absolute_value"),
                {"type": "FunnelsAlertConfig", "metric": "conversion_from_start", "funnel_step": -1},
                _base_threshold(),
                "daily",
                "funnel_step must be >= 0",
            ),
            (
                "funnels_step_out_of_range_rejected",
                _funnels_query(),  # a 2-step funnel
                _base_condition("absolute_value"),
                {"type": "FunnelsAlertConfig", "metric": "conversion_from_start", "funnel_step": 5},
                _base_threshold(),
                "daily",
                r"funnel_step 5 is out of range \(funnel has 2 steps\)",
            ),
            (
                "funnels_trends_viz_accepted",
                {**_funnels_query(), "funnelsFilter": {"funnelVizType": "trends"}},
                _base_condition("absolute_value"),
                _funnels_config(),
                _base_threshold(),
                "daily",
                None,
            ),
            (
                "funnels_time_to_convert_viz_rejected",
                {**_funnels_query(), "funnelsFilter": {"funnelVizType": "time_to_convert"}},
                _base_condition("absolute_value"),
                _funnels_config(),
                _base_threshold(),
                "daily",
                "aren't supported for the",
            ),
            (
                "funnels_flow_viz_rejected",
                {**_funnels_query(), "funnelsFilter": {"funnelVizType": "flow"}},
                _base_condition("absolute_value"),
                _funnels_config(),
                _base_threshold(),
                "daily",
                "aren't supported for the",
            ),
            (
                "funnels_trends_relative_condition_accepted",
                {**_funnels_query(), "funnelsFilter": {"funnelVizType": "trends"}},
                _base_condition("relative_increase"),
                _funnels_config(),
                _base_threshold(),
                "daily",
                None,
            ),
            (
                "funnels_steps_relative_condition_rejected",
                _funnels_query(),  # defaults to a steps funnel
                _base_condition("relative_increase"),
                _funnels_config(),
                _base_threshold(),
                "daily",
                "only supports absolute value conditions",
            ),
        ]
    )
    def test_validate_alert_config(
        self,
        _name: str,
        query: dict[str, Any],
        condition: dict[str, Any] | None,
        config: dict[str, Any] | None,
        threshold_config: dict[str, Any] | None,
        calculation_interval: str | None,
        expected_error_fragment: str | None,
    ) -> None:
        if expected_error_fragment is None:
            validate_alert_config(query, condition, config, threshold_config, calculation_interval)
        else:
            with pytest.raises(ValueError, match=expected_error_fragment):
                validate_alert_config(query, condition, config, threshold_config, calculation_interval)

    @parameterized.expand(
        [
            ("hogql", _hogql_query(), _hogql_config()),
            ("trends", _base_query(), _base_config()),
        ]
    )
    def test_threshold_alert_requires_at_least_one_bound(self, _name: str, query: dict, config: dict) -> None:
        with pytest.raises(ValueError, match="At least one threshold bound"):
            validate_alert_config(
                query,
                _base_condition(),
                config,
                _base_threshold(bounds={}),
                "daily",
            )

    def test_detector_alert_allows_empty_threshold_bounds(self) -> None:
        validate_alert_config(
            _base_query(),
            _base_condition(),
            _base_config(),
            _base_threshold(bounds={}),
            "daily",
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
        )

    def test_detector_alert_rejects_non_time_series_trend(self) -> None:
        with pytest.raises(ValueError, match="Anomaly detection isn't supported for non time series trends"):
            validate_alert_config(
                _base_query(display="ActionsPie"),
                _base_condition(),
                _base_config(),
                _base_threshold(),
                "daily",
                detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            )

    def test_any_row_hogql_alert_rejects_relative_conditions(self) -> None:
        with pytest.raises(ValueError, match="Any-row SQL alerts only support absolute value conditions"):
            validate_alert_config(
                _hogql_query(),
                _base_condition("relative_increase"),
                {"type": "HogQLAlertConfig", "evaluation": "any_row"},
                _base_threshold(type="percentage"),
                "daily",
            )

    def test_invalid_hogql_config_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid HogQLAlertConfig"):
            validate_alert_config(
                _hogql_query(),
                _base_condition(),
                {"type": "HogQLAlertConfig", "evaluation": "sideways"},
                _base_threshold(),
                "daily",
            )

    def test_hogql_config_without_evaluation_rejected(self) -> None:
        # ``evaluation`` is required — no silent default.
        with pytest.raises(ValueError, match="invalid HogQLAlertConfig"):
            validate_alert_config(
                _hogql_query(),
                _base_condition(),
                {"type": "HogQLAlertConfig"},
                _base_threshold(),
                "daily",
            )

    def test_first_row_hogql_alert_accepts_relative_conditions(self) -> None:
        # Unlike any_row, first_row is a time axis (newest first), so relative is valid.
        validate_alert_config(
            _hogql_query(),
            _base_condition("relative_increase"),
            {"type": "HogQLAlertConfig", "evaluation": "first_row"},
            _base_threshold(type="percentage"),
            "daily",
        )

    def test_detector_config_accepted_for_hogql_insight(self) -> None:
        # SQL/HogQL insights support anomaly detection (last/first-row series), so a detector_config
        # is accepted — not rejected like genuinely-unsupported kinds.
        validate_alert_config(
            _hogql_query(),
            _base_condition(),
            _hogql_config(),
            _base_threshold(),
            "daily",
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
        )

    def test_detector_config_rejected_for_any_row_hogql_alert(self) -> None:
        # any_row rows are entities, not a time series — reject anomaly detection at config time
        # so the alert can't be saved only to fail every check.
        with pytest.raises(ValueError, match="Anomaly detection isn't supported for any-row SQL alerts"):
            validate_alert_config(
                _hogql_query(),
                _base_condition(),
                {"type": "HogQLAlertConfig", "evaluation": "any_row"},
                _base_threshold(),
                "daily",
                detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            )

    def test_detector_config_rejected_for_unsupported_insight(self) -> None:
        # Funnels have no detector extractor, so a detector_config is rejected at config time.
        with pytest.raises(ValueError, match="Anomaly detection alerts aren't supported"):
            validate_alert_config(
                {"kind": "FunnelsQuery", "series": [{"kind": "EventsNode", "event": "a"}]},
                _base_condition(),
                {"type": "FunnelsAlertConfig", "metric": "conversion_from_start", "funnel_step": None},
                _base_threshold(),
                "daily",
                detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            )

    def test_skips_threshold_bounds_when_not_required(self) -> None:
        validate_alert_config(
            _base_query(),
            _base_condition(),
            _base_config(),
            _base_threshold(bounds={}),
            "daily",
            require_threshold_bounds=False,
        )


VALID_FORECAST = {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach", "horizon": 7}
TRENDS_QUERY = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]}
TRENDS_CONFIG = {"type": "TrendsAlertConfig", "series_index": 0}
ABS_THRESHOLD = {"type": "absolute", "bounds": {"upper": 100}}


class TestForecastConfigValidation:
    @parameterized.expand(
        [
            ("horizon_zero", {**VALID_FORECAST, "horizon": 0}, "horizon"),
            ("horizon_reaches_past_the_cap", {**VALID_FORECAST, "horizon": 200}, "at most 6 months"),
            ("bad_interval_width", {**VALID_FORECAST, "interval_width": 1.5}, "interval_width"),
            ("unknown_engine", {**VALID_FORECAST, "engine": "chronos"}, "engine"),
            ("unknown_condition", {**VALID_FORECAST, "condition": "nope"}, "condition"),
        ]
    )
    def test_invalid_forecast_config_rejected(self, _name: str, forecast_config: dict, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            validate_alert_config(
                TRENDS_QUERY,
                {"type": "absolute_value"},
                TRENDS_CONFIG,
                ABS_THRESHOLD,
                calculation_interval="daily",
                forecast_config=forecast_config,
            )

    def test_valid_forecast_config_accepted(self) -> None:
        validate_alert_config(
            TRENDS_QUERY,
            {"type": "absolute_value"},
            TRENDS_CONFIG,
            ABS_THRESHOLD,
            calculation_interval="daily",
            forecast_config=VALID_FORECAST,
        )

    def test_forecast_and_detector_mutually_exclusive(self) -> None:
        with pytest.raises(ValueError, match="both"):
            validate_alert_config(
                TRENDS_QUERY,
                {"type": "absolute_value"},
                TRENDS_CONFIG,
                ABS_THRESHOLD,
                calculation_interval="daily",
                detector_config={"type": "zscore"},
                forecast_config=VALID_FORECAST,
            )

    def test_future_breach_requires_threshold_bounds(self) -> None:
        with pytest.raises(ValueError, match="threshold"):
            validate_alert_config(
                TRENDS_QUERY,
                {"type": "absolute_value"},
                TRENDS_CONFIG,
                None,
                calculation_interval="daily",
                forecast_config=VALID_FORECAST,
            )

    def test_band_deviation_needs_no_threshold(self) -> None:
        validate_alert_config(
            TRENDS_QUERY,
            {"type": "absolute_value"},
            TRENDS_CONFIG,
            None,
            calculation_interval="daily",
            forecast_config={"type": "ForecastConfig", "engine": "prophet", "condition": "band_deviation"},
        )

    def test_forecast_rejects_non_trends(self) -> None:
        with pytest.raises(ValueError, match="[Ff]orecast"):
            validate_alert_config(
                {"kind": "HogQLQuery", "query": "select 1"},
                {"type": "absolute_value"},
                {"type": "HogQLAlertConfig", "evaluation": "last_row"},
                ABS_THRESHOLD,
                calculation_interval="daily",
                forecast_config=VALID_FORECAST,
            )

    @parameterized.expand(
        [
            ("single", {"breakdown": "$browser", "breakdown_type": "event"}),
            ("multi", {"breakdowns": [{"property": "$browser", "type": "event"}]}),
        ]
    )
    def test_forecast_rejects_breakdown(self, _name: str, breakdown_filter: dict) -> None:
        query = {**TRENDS_QUERY, "breakdownFilter": breakdown_filter}
        with pytest.raises(ValueError, match="breakdown"):
            validate_alert_config(
                query,
                {"type": "absolute_value"},
                TRENDS_CONFIG,
                ABS_THRESHOLD,
                calculation_interval="daily",
                forecast_config=VALID_FORECAST,
            )

    @parameterized.expand(
        [
            ("hour", "hour", 7),
            ("day", "day", 7),
            ("week", "week", 7),
            ("month", "month", 6),
        ]
    )
    def test_forecast_accepts_supported_intervals(self, _name: str, interval: str, horizon: int) -> None:
        validate_alert_config(
            {**TRENDS_QUERY, "interval": interval},
            {"type": "absolute_value"},
            TRENDS_CONFIG,
            ABS_THRESHOLD,
            calculation_interval="daily",
            forecast_config={**VALID_FORECAST, "horizon": horizon},
        )

    @parameterized.expand(
        [
            ("7 weeks is fine", "week", 7, True),
            ("7 months reaches 213 days", "month", 7, False),
            ("6 months is the most that fits", "month", 6, True),
        ]
    )
    def test_horizon_cap_binds_by_reach_not_count(
        self, _name: str, interval: str, horizon: int, accepted: bool
    ) -> None:
        def run() -> None:
            validate_alert_config(
                {**TRENDS_QUERY, "interval": interval},
                {"type": "absolute_value"},
                TRENDS_CONFIG,
                ABS_THRESHOLD,
                calculation_interval="daily",
                forecast_config={**VALID_FORECAST, "horizon": horizon},
            )

        if accepted:
            run()
        else:
            with pytest.raises(ValueError, match="at most 6 months"):
                run()

    @parameterized.expand(
        [
            ("minute", "minute"),
            ("quarter", "quarter"),
            ("year", "year"),
        ]
    )
    def test_forecast_rejects_unsupported_intervals(self, _name: str, interval: str) -> None:
        with pytest.raises(ValueError, match="hourly, daily, weekly"):
            validate_alert_config(
                {**TRENDS_QUERY, "interval": interval},
                {"type": "absolute_value"},
                TRENDS_CONFIG,
                ABS_THRESHOLD,
                calculation_interval="daily",
                forecast_config=VALID_FORECAST,
            )

    def test_future_breach_rejects_percentage_threshold(self) -> None:
        with pytest.raises(ValueError, match="absolute threshold"):
            validate_alert_config(
                TRENDS_QUERY,
                {"type": "relative_increase"},
                TRENDS_CONFIG,
                {"type": "percentage", "bounds": {"upper": 0.2}},
                calculation_interval="daily",
                forecast_config=VALID_FORECAST,
            )

    def test_band_deviation_allows_percentage_threshold(self) -> None:
        validate_alert_config(
            TRENDS_QUERY,
            {"type": "relative_increase"},
            TRENDS_CONFIG,
            {"type": "percentage", "bounds": {"upper": 0.2}},
            calculation_interval="daily",
            forecast_config={**VALID_FORECAST, "condition": "band_deviation"},
        )

    @parameterized.expand(
        [
            ("missing target", {"target_direction": "at_least", "target_date": "2026-12-31"}, "needs a target value"),
            ("missing direction", {"target": 100, "target_date": "2026-12-31"}, "at least, or at most"),
            ("missing date", {"target": 100, "target_direction": "at_least"}, "needs a target date"),
            (
                "past date",
                {"target": 100, "target_direction": "at_least", "target_date": "2020-01-01"},
                "in the future",
            ),
            (
                "beyond the cap",
                {"target": 100, "target_direction": "at_least", "target_date": "2030-01-01"},
                "within 6 months",
            ),
        ]
    )
    def test_target_by_date_config_is_rejected(self, _name: str, extra: dict, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            validate_alert_config(
                TRENDS_QUERY,
                {"type": "absolute_value"},
                TRENDS_CONFIG,
                ABS_THRESHOLD,
                calculation_interval="daily",
                forecast_config={
                    "type": "ForecastConfig",
                    "engine": "prophet",
                    "condition": "target_by_date",
                    **extra,
                },
                require_future_target_date=True,
            )

    def test_a_finished_target_alert_still_validates(self) -> None:
        validate_alert_config(
            TRENDS_QUERY,
            {"type": "absolute_value"},
            TRENDS_CONFIG,
            ABS_THRESHOLD,
            calculation_interval="daily",
            forecast_config={
                "type": "ForecastConfig",
                "engine": "prophet",
                "condition": "target_by_date",
                "target": 100,
                "target_direction": "at_least",
                "target_date": "2020-01-01",
            },
        )

    def test_target_by_date_config_is_accepted(self) -> None:
        target_date = (datetime.now(UTC).date() + timedelta(days=90)).isoformat()
        validate_alert_config(
            TRENDS_QUERY,
            {"type": "absolute_value"},
            TRENDS_CONFIG,
            ABS_THRESHOLD,
            calculation_interval="daily",
            forecast_config={
                "type": "ForecastConfig",
                "engine": "prophet",
                "condition": "target_by_date",
                "target": 10000,
                "target_direction": "at_least",
                "target_date": target_date,
            },
        )

    @parameterized.expand(
        [
            ("relative with no percentage", {"error_mode": "relative"}, "needs a percentage"),
            ("relative out of range", {"error_mode": "relative", "error_threshold_pct": 20}, "between 0 and 1000"),
            ("absolute with no amount", {"error_mode": "absolute"}, "needs an amount"),
            ("absolute not positive", {"error_mode": "absolute", "error_threshold_abs": 0}, "more than 0"),
            ("score out of range", {"score_threshold": 5}, "between 0 and 3"),
        ]
    )
    def test_band_deviation_modes_are_rejected(self, _name: str, extra: dict, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            validate_alert_config(
                TRENDS_QUERY,
                {"type": "absolute_value"},
                TRENDS_CONFIG,
                ABS_THRESHOLD,
                calculation_interval="daily",
                forecast_config={
                    "type": "ForecastConfig",
                    "engine": "prophet",
                    "condition": "band_deviation",
                    **extra,
                },
            )

    @parameterized.expand(
        [
            ("percentage mode", {"error_mode": "relative", "error_threshold_pct": 0.2}),
            ("fixed amount mode", {"error_mode": "absolute", "error_threshold_abs": 50}),
            ("interval mode with a score", {"score_threshold": 0.5}),
            ("interval mode with a quiet score", {"score_threshold": 2.5}),
            ("direction only", {"direction": "above"}),
        ]
    )
    def test_band_deviation_modes_are_accepted(self, _name: str, extra: dict) -> None:
        validate_alert_config(
            TRENDS_QUERY,
            {"type": "absolute_value"},
            TRENDS_CONFIG,
            ABS_THRESHOLD,
            calculation_interval="daily",
            forecast_config={
                "type": "ForecastConfig",
                "engine": "prophet",
                "condition": "band_deviation",
                **extra,
            },
        )
