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
