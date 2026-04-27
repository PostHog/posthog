from typing import Any

import pytest

from parameterized import parameterized

from posthog.tasks.alerts.utils import validate_alert_config


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


def _base_threshold(type: str = "absolute", bounds: dict[str, Any] | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {"type": type}
    if bounds is not None:
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
