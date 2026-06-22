import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import HogQLAlertConfig

from posthog.tasks.alerts.detector import _compute_min_samples_for_detector

from products.alerts.backend.evaluation.contract import AlertExtractionError
from products.alerts.backend.evaluation.detector import evaluate_with_detector
from products.alerts.backend.evaluation.hogql import (
    LAST_ROW_MAX_ROWS,
    HogQLDetectorExtractor,
    extract_hogql_detector_series,
)

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


@pytest.mark.parametrize(
    "latest,expect_anomaly",
    [
        (100.0, True),  # a spike far outside the stable baseline fires
        (1.1, False),  # a value within the baseline range does not
    ],
)
def test_scores_the_latest_value(latest, expect_anomaly):
    evaluation = evaluate_with_detector(_extract([*STABLE_HISTORY, latest]), ZSCORE)
    assert evaluation.value == latest
    assert bool(evaluation.breaches) is expect_anomaly
    if expect_anomaly:
        assert evaluation.breaches and "Anomaly detected" in evaluation.breaches[0]


def test_large_result_is_bounded_to_the_detector_window():
    # A big SQL result must not train the detector on every point — only the most recent window
    # it needs (the latest point is preserved as "current"), so workers can't be made to score
    # tens of thousands of points each check.
    expected = _compute_min_samples_for_detector(ZSCORE) + 1
    result = _extract([float(i % 5) for i in range(500)] + [999.0])  # 501 rows
    assert len(result.series[0].points) == expected
    assert result.series[0].points[-1].value == 999.0


def test_last_row_truncation_guard_rejects_a_capped_result():
    # last_row scores the tail; a result at HogQL's hard cap may be truncated, so the detector path
    # must fail loud just like the threshold extractor rather than score a wrong "current" row.
    with pytest.raises(AlertExtractionError, match="may be truncated"):
        _extract([[1.0]] * LAST_ROW_MAX_ROWS, columns=["value"])


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


def test_extract_hogql_detector_series_is_alert_less():
    # The simulation reuses the alert-less builder directly (no AlertConfiguration).
    config = HogQLAlertConfig(type="HogQLAlertConfig", evaluation="last_row")
    with patch(CALC_PATH) as calc:
        calc.return_value = MagicMock(result=[[v] for v in [*STABLE_HISTORY, 100.0]], columns=None)
        result = extract_hogql_detector_series(MagicMock(), MagicMock(), config, ZSCORE, user=None)
    assert len(result.series[0].points) == 32
    assert evaluate_with_detector(result, ZSCORE).value == 100.0
