import pytest
from unittest.mock import MagicMock, patch

from products.alerts.backend.evaluation.contract import AlertExtractionError
from products.alerts.backend.evaluation.detector import evaluate_with_detector
from products.alerts.backend.evaluation.hogql import HogQLDetectorExtractor

CALC_PATH = "products.alerts.backend.evaluation.hogql.calculate_for_query_based_insight"
ZSCORE = {"type": "zscore", "threshold": 0.9, "window": 5}

# zscore floors min-samples at 31, so a scoreable series needs >=32 rows. Build a stable-ish
# history (non-zero variance) so the detector has a baseline to flag a spike against.
STABLE_HISTORY = [round(1.0 + (i % 3) * 0.1, 2) for i in range(31)]


def _alert(rows_config: dict | None = None, detector_config: dict | None = ZSCORE) -> MagicMock:
    alert = MagicMock()
    alert.config = {"type": "HogQLAlertConfig", "evaluation": "last_row", **(rows_config or {})}
    alert.detector_config = detector_config
    return alert


def _extract(values, *, columns=None, rows_config=None, detector_config=ZSCORE):
    rows = [[v] for v in values] if columns is None else values
    with patch(CALC_PATH) as calc:
        calc.return_value = MagicMock(result=rows, columns=columns)
        return HogQLDetectorExtractor().extract(_alert(rows_config, detector_config), MagicMock(), MagicMock())


def test_detects_anomalous_last_value():
    result = _extract([*STABLE_HISTORY, 100.0])
    evaluation = evaluate_with_detector(result, ZSCORE)
    assert evaluation.value == 100.0
    assert evaluation.breaches and "Anomaly detected" in evaluation.breaches[0]


def test_no_anomaly_when_latest_is_in_range():
    result = _extract([*STABLE_HISTORY, 1.1])
    evaluation = evaluate_with_detector(result, ZSCORE)
    assert evaluation.value == 1.1
    assert evaluation.breaches == []


def test_first_row_reverses_so_the_head_is_current():
    # first_row results are newest-first; the spike at the head must be scored as the current value.
    result = _extract([100.0, *STABLE_HISTORY], rows_config={"evaluation": "first_row"})
    evaluation = evaluate_with_detector(result, ZSCORE)
    assert evaluation.value == 100.0
    assert evaluation.breaches and "Anomaly detected" in evaluation.breaches[0]


def test_too_few_rows_is_uncomputed():
    result = _extract([1.0, 1.1, 1.0, 1.2, 1.0])  # < 32 → can't score
    assert result.series == []
    evaluation = evaluate_with_detector(result, ZSCORE)
    assert evaluation.value is None
    assert evaluation.breaches == []


def test_empty_result_is_zero():
    result = _extract([])
    assert result.empty_query_result is True
    evaluation = evaluate_with_detector(result, ZSCORE)
    assert evaluation.value == 0


def test_any_row_not_supported():
    with pytest.raises(AlertExtractionError, match="any-row"):
        _extract([*STABLE_HISTORY, 100.0], rows_config={"evaluation": "any_row"})


def test_picks_numeric_column_and_labels_by_its_name():
    rows = [["2026-06-01", v] for v in [*STABLE_HISTORY, 100.0]]
    result = _extract(rows, columns=["day", "value"])
    assert result.series[0].label == "value"
    evaluation = evaluate_with_detector(result, ZSCORE)
    assert evaluation.value == 100.0
