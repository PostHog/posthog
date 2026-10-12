from datetime import UTC, date, datetime, timedelta

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import HogQLAlertConfig

from posthog.api.services.query import ExecutionMode
from posthog.tasks.alerts.detector import _compute_min_samples_for_detector

from products.alerts.backend.evaluation.contract import AlertDataUnavailableError, AlertExtractionError
from products.alerts.backend.evaluation.detector import evaluate_with_detector
from products.alerts.backend.evaluation.hogql import (
    LAST_ROW_MAX_ROWS,
    HogQLDetectorExtractor,
    _explicit_limit,
    extract_hogql_detector_series,
)

CALC_PATH = "products.alerts.backend.evaluation.hogql.calculate_for_query_based_insight"
ZSCORE = {"type": "zscore", "threshold": 0.9, "window": 5}
EXEC_MODE = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE

# zscore floors min-samples at 31, so STABLE_HISTORY is exactly the detector minimum. Non-zero
# variance gives the detector a baseline to flag a spike against.
STABLE_HISTORY = [round(1.0 + (i % 3) * 0.1, 2) for i in range(31)]
_LATEST = len(STABLE_HISTORY)  # index of the appended (evaluated) row in [*STABLE_HISTORY, latest]


def _alert(rows_config: dict | None = None, detector_config: dict | None = ZSCORE) -> MagicMock:
    alert = MagicMock()
    alert.config = {"type": "HogQLAlertConfig", "evaluation": "last_row", **(rows_config or {})}
    alert.detector_config = detector_config
    return alert


def _extract(values, *, columns=None, rows_config=None, detector_config=ZSCORE, query=None):
    rows = [[v] for v in values] if columns is None else values
    with patch(CALC_PATH) as calc:
        calc.return_value = MagicMock(result=rows, columns=columns, has_more=False)
        return HogQLDetectorExtractor().extract(
            _alert(rows_config, detector_config), MagicMock(query=query), MagicMock(), EXEC_MODE
        )


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


@pytest.mark.parametrize("evaluation", ["first_row", "last_row"])
@pytest.mark.parametrize("label_type", ["date", "datetime", "native_date", "native_datetime", "invalid", "missing"])
def test_large_result_is_bounded_to_the_detector_window(evaluation, label_type):
    # A big SQL result must not train the detector on every point — only the most recent window
    # it needs (the latest point is preserved as "current"), so workers can't be made to score
    # tens of thousands of points each check.
    expected = _compute_min_samples_for_detector(ZSCORE)
    row_count = 501
    assert expected < row_count  # guard: the fixture must exceed the window or this test is moot
    labels: list[str | date | None] = []
    for i in range(row_count):
        timestamp = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=i)
        label_options: dict[str, str | date | None] = {
            "date": timestamp.date().isoformat(),
            "datetime": timestamp.isoformat(),
            "native_date": timestamp.date(),
            "native_datetime": timestamp,
            "invalid": "not a date" if i == row_count - 2 else timestamp.date().isoformat(),
            "missing": None,
        }
        labels.append(label_options[label_type])
    values = [float(i % 5) for i in range(row_count - 1)] + [999.0]
    rows = [[label, value] for label, value in zip(labels, values)]
    if evaluation == "first_row":
        rows.reverse()
    result = _extract(rows, columns=["day", "value"], rows_config={"evaluation": evaluation})
    assert len(result.series[0].points) == expected  # bounded to the window, not the full result
    assert result.series[0].points[-1].value == 999.0  # latest row preserved as current
    if label_type in ("invalid", "missing"):
        assert all(point.date is None for point in result.series[0].points)
    else:
        expected_dates = [label.isoformat() if isinstance(label, date) else label for label in labels[-expected:]]
        assert [point.date for point in result.series[0].points] == expected_dates


@pytest.mark.parametrize("sql", ["SELECT value FROM events", "SELECT value FROM events LIMIT 6"])
def test_a_short_sql_series_still_reaches_the_ai_judge(sql):
    llm = {"type": "llm", "threshold": 0.7, "window": 90}
    result = _extract([1.0, 2.0, 1.0, 2.0, 1.0, 9.0], detector_config=llm, query={"kind": "HogQLQuery", "query": sql})
    assert len(result.series[0].points) == 6
    with pytest.raises(AlertDataUnavailableError, match="at least 5 rows"):
        _extract([1.0, 2.0, 1.0, 9.0], detector_config=llm)
    with pytest.raises(AlertDataUnavailableError, match="at least 31 rows"):
        _extract([1.0, 2.0, 1.0, 2.0, 1.0, 9.0], detector_config=ZSCORE)


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


def test_exactly_the_detector_minimum_is_scored():
    # A result with exactly the detector's minimum row count must be scored, not rejected as "not
    # enough data". Regression: the cutoff previously required one row more than the detector needs.
    minimum = _compute_min_samples_for_detector(ZSCORE)
    rows = [*STABLE_HISTORY[: minimum - 1], 100.0]  # exactly `minimum` rows, spike last
    assert len(rows) == minimum
    evaluation = evaluate_with_detector(_extract(rows), ZSCORE)
    assert evaluation.value == 100.0
    assert evaluation.breaches and "Anomaly detected" in evaluation.breaches[0]


def test_one_row_below_the_detector_minimum_reports_insufficient_history():
    minimum = _compute_min_samples_for_detector(ZSCORE)
    with pytest.raises(AlertDataUnavailableError, match=f"at least {minimum} rows"):
        _extract(STABLE_HISTORY[: minimum - 1])


def test_threshold_detector_scores_a_single_row():
    # The threshold detector needs only one point, so a one-row SQL result must score and can fire —
    # not be silently rejected. Regression for the same off-by-one at the minimum=1 extreme.
    config = {"type": "threshold", "upper_bound": 10.0}
    result = _extract([[500.0]], columns=["value"], detector_config=config)
    assert len(result.series[0].points) == 1
    evaluation = evaluate_with_detector(result, config)
    assert evaluation.value == 500.0
    assert evaluation.breaches and "Anomaly detected" in evaluation.breaches[0]


def test_empty_result_is_zero():
    result = _extract([])
    assert result.empty_query_result is True
    evaluation = evaluate_with_detector(result, ZSCORE)
    assert evaluation.value == 0


def test_any_row_not_supported():
    with pytest.raises(AlertExtractionError, match="any-row"):
        _extract([*STABLE_HISTORY, 100.0], rows_config={"evaluation": "any_row"})


# The evaluated (latest) row's label, like the threshold path: explicit label_column, else the first
# non-evaluated column, else the value-column name (never "row N").
@pytest.mark.parametrize(
    "columns,rows_config,row_fn,expected_label",
    [
        (["metric", "value"], None, lambda i, v: [f"m{i}", v], f"m{_LATEST}"),  # first non-evaluated column
        (["id", "note", "value"], {"label_column": "id"}, lambda i, v: [f"r{i}", "x", v], f"r{_LATEST}"),  # explicit
        (["value"], None, lambda i, v: [v], "value"),  # single column → value-column name
    ],
)
def test_labels_evaluated_row(columns, rows_config, row_fn, expected_label):
    rows = [row_fn(i, v) for i, v in enumerate([*STABLE_HISTORY, 100.0])]
    result = _extract(rows, columns=columns, rows_config=rows_config)
    assert result.series[0].label == expected_label


def test_extract_hogql_detector_series_is_alert_less():
    # The simulation reuses the alert-less builder directly (no AlertConfiguration).
    config = HogQLAlertConfig(type="HogQLAlertConfig", evaluation="last_row")
    with patch(CALC_PATH) as calc:
        calc.return_value = MagicMock(result=[[v] for v in [*STABLE_HISTORY, 100.0]], columns=None, has_more=False)
        result = extract_hogql_detector_series(
            MagicMock(), MagicMock(), config, ZSCORE, user=None, execution_mode=EXEC_MODE
        )
    assert len(result.series[0].points) == _compute_min_samples_for_detector(ZSCORE)  # bounded to the minimum
    assert evaluate_with_detector(result, ZSCORE).value == 100.0


@pytest.mark.parametrize("evaluation", ["last_row", "first_row"])
@pytest.mark.parametrize("row_count", [0, 5, 25])
def test_explicit_limit_below_detector_minimum_is_a_configuration_error(evaluation, row_count):
    insight = MagicMock(query={"kind": "HogQLQuery", "query": "SELECT 1 AS value LIMIT 25"})
    with patch(CALC_PATH, return_value=MagicMock(result=[[1.0]] * row_count, columns=["value"], has_more=False)):
        with pytest.raises(AlertExtractionError, match="LIMIT.*25.*at least 31") as exc:
            HogQLDetectorExtractor().extract(_alert({"evaluation": evaluation}), insight, insight.query, EXEC_MODE)
    assert type(exc.value) is AlertExtractionError


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT 1 LIMIT 25", 25),
        ("SELECT 1", None),
        ("SELECT 1 LIMIT {n}", None),
        ("not valid sql", None),
        ("SELECT 1 LIMIT 0", 0),
    ],
)
@pytest.mark.parametrize("wrapped", [False, True])
def test_saved_query_explicit_limit(sql, expected, wrapped):
    query = {"kind": "HogQLQuery", "query": sql}
    if wrapped:
        query = {"kind": "DataVisualizationNode", "source": query}
    assert _explicit_limit(MagicMock(query=query)) == expected
