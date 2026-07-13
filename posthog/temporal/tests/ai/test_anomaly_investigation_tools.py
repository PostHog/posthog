from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.ai.anomaly_investigation.tools import _run_detector_simulation


@parameterized.expand(
    [
        ("configured_series", {"type": "TrendsAlertConfig", "series_index": 2}, 2),
        ("missing_series_index", {"type": "TrendsAlertConfig"}, 0),
        ("null_config", None, 0),
    ]
)
def test_run_detector_simulation_forwards_series_index(_name, config, expected_series_index) -> None:
    alert = MagicMock()
    alert.config = config
    alert.detector_config = {"type": "zscore", "threshold": 0.95}

    with patch(
        "products.alerts.backend.evaluation.detector.simulate_detector_on_insight",
        return_value={"data": [], "dates": []},
    ) as mock_simulate:
        _run_detector_simulation(alert=alert, team=MagicMock(), date_from=None)

    assert mock_simulate.call_args.kwargs["series_index"] == expected_series_index
