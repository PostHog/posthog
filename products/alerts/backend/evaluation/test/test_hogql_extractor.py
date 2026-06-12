import re
from decimal import Decimal
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import (
    AlertCondition,
    AlertConditionType,
    InsightsThresholdBounds,
    InsightThreshold,
    InsightThresholdType,
)

from products.alerts.backend.evaluation.comparator import evaluate_threshold
from products.alerts.backend.evaluation.contract import AlertExtractionError
from products.alerts.backend.evaluation.hogql import ANY_ROW_MAX_ROWS, HogQLExtractor, _resolve_value_column_index

CALC_PATH = "products.alerts.backend.evaluation.hogql.calculate_for_query_based_insight"

ABSOLUTE = AlertCondition(type=AlertConditionType.ABSOLUTE_VALUE)


def _alert(condition_type=AlertConditionType.ABSOLUTE_VALUE, config: dict | None = None):
    alert = MagicMock()
    alert.condition = {"type": condition_type}
    alert.config = config or {"type": "HogQLAlertConfig"}
    return alert


def _threshold(type_=InsightThresholdType.ABSOLUTE, lower=None, upper=None):
    return InsightThreshold(type=type_, bounds=InsightsThresholdBounds(lower=lower, upper=upper))


def _extract(rows, *, columns=None, condition_type=AlertConditionType.ABSOLUTE_VALUE, config: dict | None = None):
    with patch(CALC_PATH) as calc:
        calc.return_value = MagicMock(result=rows, columns=columns)
        return HogQLExtractor().extract(_alert(condition_type, config), MagicMock(), MagicMock())


# ---- result shape handling ----


def test_none_result_raises_runtime_error():
    # A None result means the query layer swallowed an error — raise (not AlertExtractionError) to
    # avoid a misfire, matching the trends extractor.
    with pytest.raises(RuntimeError, match="No results found"):
        _extract(None)


def test_non_list_shape_raises_distinct_error():
    with pytest.raises(AlertExtractionError, match="unexpected result shape"):
        _extract({"not": "a list"})


def test_non_list_rows_raise():
    with pytest.raises(AlertExtractionError, match="rows as lists/tuples"):
        _extract([{"a": 1}])


@pytest.mark.parametrize("bad", ["text", True])
def test_non_numeric_value_raises(bad):
    with pytest.raises(AlertExtractionError, match="numeric value"):
        _extract([[bad]])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_rejects_non_finite(bad):
    with pytest.raises(AlertExtractionError, match="finite numeric value"):
        _extract([[bad]])


def test_none_bucket_becomes_zero():
    result = _extract([[None]])
    assert [p.value for p in result.series[0].points] == [0.0]


def test_accepts_decimal_columns():
    # ClickHouse Decimal columns surface as decimal.Decimal — they are valid numeric values.
    result = _extract([[Decimal("41.5")], [Decimal("42.0")]])
    assert [p.value for p in result.series[0].points] == [41.5, 42.0]


# ---- empty result = 0, matching trends ----


@pytest.mark.parametrize(
    "condition_type",
    [AlertConditionType.ABSOLUTE_VALUE, AlertConditionType.RELATIVE_INCREASE],
)
def test_empty_result_evaluates_as_zero_and_can_breach_lower_bound(condition_type):
    result = _extract([], condition_type=condition_type)
    assert result.empty_query_result is True
    breach = evaluate_threshold(result, AlertCondition(type=condition_type), _threshold(lower=5))
    assert breach.value == 0.0
    assert breach.breaches is not None and len(breach.breaches) == 1
    no_breach = evaluate_threshold(result, AlertCondition(type=condition_type), _threshold(lower=-5))
    assert no_breach.value == 0.0
    assert no_breach.breaches == []


def test_any_row_cap_matches_the_frontend_mirror():
    # The preview mirror (see the PREVIEW MIRROR CONTRACT on HogQLExtractor) duplicates the
    # any-row cap as a TS constant; pin the two values together so a one-sided bump fails CI.
    mirror = (
        Path(__file__).parents[5] / "frontend" / "src" / "lib" / "components" / "Alerts" / "alertFormLogic.ts"
    ).read_text()
    match = re.search(r"HOGQL_ANY_ROW_MAX_ROWS = (\d+)", mirror)
    assert match, "HOGQL_ANY_ROW_MAX_ROWS not found in the frontend mirror"
    assert int(match.group(1)) == ANY_ROW_MAX_ROWS


def test_evaluation_uses_saved_variable_values_not_session_overrides():
    # The alert path passes no variables_override, so a variable-using SQL query evaluates with
    # the values saved on the query (or each variable's default) — session-level UI overrides
    # never reach evaluation. This is why the configure-time preview (which reads the user's
    # possibly-overridden cached result) can disagree with what the alert actually evaluates.
    with patch(CALC_PATH) as calc:
        calc.return_value = MagicMock(result=[[5]], columns=["count"])
        HogQLExtractor().extract(_alert(), MagicMock(), MagicMock())
    assert "variables_override" not in calc.call_args.kwargs


# ---- column selection ----


def test_single_column_needs_no_metadata():
    result = _extract([[10], [42]])
    assert [p.value for p in result.series[0].points] == [10.0, 42.0]
    assert result.series[0].label == "result"


def test_single_numeric_column_heuristic_skips_date_column():
    # The common charted shape: SELECT day, value ORDER BY day — evaluate the numeric column.
    rows = [["2024-01-01", 10], ["2024-01-02", 42]]
    result = _extract(rows, columns=["day", "value"])
    assert [p.value for p in result.series[0].points] == [10.0, 42.0]
    assert result.series[0].label == "value"


def test_multiple_numeric_columns_require_explicit_pick():
    with pytest.raises(AlertExtractionError, match="pick the column"):
        _extract([[1, 2]], columns=["a", "b"])


def test_no_numeric_column_raises():
    with pytest.raises(AlertExtractionError, match="pick the column"):
        _extract([["x", "y"]], columns=["a", "b"])


def test_explicit_column_pick():
    rows = [["2024-01-01", 1, 10], ["2024-01-02", 2, 42]]
    result = _extract(rows, columns=["day", "errors", "total"], config={"type": "HogQLAlertConfig", "column": "total"})
    assert [p.value for p in result.series[0].points] == [10.0, 42.0]
    assert result.series[0].label == "total"


def test_explicit_column_not_in_result_raises():
    with pytest.raises(AlertExtractionError, match="not in the result columns"):
        _extract([[1]], columns=["count"], config={"type": "HogQLAlertConfig", "column": "missing"})


def test_explicit_column_without_metadata_raises():
    with pytest.raises(AlertExtractionError, match="no column metadata"):
        _extract([[1]], config={"type": "HogQLAlertConfig", "column": "count"})


def test_heuristic_classifies_by_most_recent_non_none_value():
    # A column whose latest value is None is classified by the most recent non-None one.
    assert _resolve_value_column_index(None, ["a", "b"], [["x", 1], ["y", None]]) == 1


def test_all_none_column_is_not_numeric():
    # An all-None column can't be classified, so the other (numeric) column wins.
    assert _resolve_value_column_index(None, ["a", "b"], [[None, 1], [None, 2]]) == 1


# ---- last_row evaluation (default) ----


def test_builds_unframed_single_series():
    result = _extract([[10], [42]])
    assert result.framed is False and result.is_breakdown is False
    assert result.subject == "The SQL insight value"
    assert result.series[0].current_index == 1  # last row is the anchor


def test_absolute_alert_breaches_on_last_row():
    result = _extract([[10], [200]])
    evaluation = evaluate_threshold(result, ABSOLUTE, _threshold(upper=100))
    assert evaluation.value == 200.0
    assert evaluation.breaches is not None
    assert evaluation.breaches[0] == "The SQL insight value (200.0) is more than upper threshold (100.0)"


def test_relative_alert_needs_two_rows():
    with pytest.raises(AlertExtractionError, match="at least two rows"):
        _extract([[5]], condition_type=AlertConditionType.RELATIVE_INCREASE)


# ---- any_row evaluation ----


def test_any_row_breaches_on_any_value_with_row_label():
    rows = [["US", 0.1], ["DE", 0.4], ["FR", 0.2]]
    result = _extract(
        rows, columns=["country", "error_rate"], config={"type": "HogQLAlertConfig", "evaluation": "any_row"}
    )
    assert result.is_breakdown is True
    assert [s.label for s in result.series] == ["US", "DE", "FR"]
    evaluation = evaluate_threshold(result, ABSOLUTE, _threshold(upper=0.25))
    assert evaluation.value == 0.4
    assert evaluation.breaches is not None
    assert evaluation.breaches[0] == "The SQL insight value (DE) (0.4) is more than upper threshold (0.25)"


def test_any_row_no_breach_reports_no_value():
    rows = [["US", 0.1], ["DE", 0.2]]
    result = _extract(
        rows, columns=["country", "error_rate"], config={"type": "HogQLAlertConfig", "evaluation": "any_row"}
    )
    evaluation = evaluate_threshold(result, ABSOLUTE, _threshold(upper=0.5))
    assert evaluation.breaches == []
    assert evaluation.value is None  # several rows — no single representative value


def test_any_row_explicit_label_column():
    rows = [["US", "prod", 5], ["DE", "dev", 50]]
    result = _extract(
        rows,
        columns=["country", "env", "errors"],
        config={"type": "HogQLAlertConfig", "evaluation": "any_row", "column": "errors", "label_column": "env"},
    )
    assert [s.label for s in result.series] == ["prod", "dev"]


def test_any_row_label_falls_back_to_row_number():
    result = _extract([[5], [50]], config={"type": "HogQLAlertConfig", "evaluation": "any_row"})
    assert [s.label for s in result.series] == ["row 1", "row 2"]


def test_any_row_missing_label_column_raises():
    with pytest.raises(AlertExtractionError, match="label column"):
        _extract(
            [[1]],
            columns=["count"],
            config={"type": "HogQLAlertConfig", "evaluation": "any_row", "label_column": "missing"},
        )


def test_any_row_reports_every_breaching_row():
    rows = [["US", 0.1], ["DE", 0.4], ["FR", 0.3], ["BR", 0.5]]
    result = _extract(
        rows, columns=["country", "error_rate"], config={"type": "HogQLAlertConfig", "evaluation": "any_row"}
    )
    evaluation = evaluate_threshold(result, ABSOLUTE, _threshold(upper=0.25))
    assert evaluation.value == 0.4  # the first breaching value
    assert evaluation.breaches == [
        "The SQL insight value (DE) (0.4) is more than upper threshold (0.25)",
        "The SQL insight value (FR) (0.3) is more than upper threshold (0.25)",
        "The SQL insight value (BR) (0.5) is more than upper threshold (0.25)",
    ]
    # Which rows breached is persisted on the check record — notifications are transient.
    assert evaluation.triggered_metadata == {
        "breaching_rows": [
            {"label": "DE", "value": 0.4},
            {"label": "FR", "value": 0.3},
            {"label": "BR", "value": 0.5},
        ],
        "breaching_row_count": 3,
    }


def test_any_row_breach_list_is_capped():
    rows = [[f"r{i}", 10.0] for i in range(8)]
    result = _extract(rows, columns=["name", "value"], config={"type": "HogQLAlertConfig", "evaluation": "any_row"})
    evaluation = evaluate_threshold(result, ABSOLUTE, _threshold(upper=5))
    assert evaluation.breaches is not None and len(evaluation.breaches) == 6  # 5 rows + the overflow note
    assert evaluation.breaches[-1] == "...and 3 more rows breach"


def test_any_row_accepts_exactly_the_row_cap():
    rows = [[float(i)] for i in range(1000)]
    result = _extract(rows, config={"type": "HogQLAlertConfig", "evaluation": "any_row"})
    assert len(result.series) == 1000


def test_any_row_rejects_too_many_rows():
    rows = [[float(i)] for i in range(1001)]
    with pytest.raises(AlertExtractionError, match="at most 1000 rows"):
        _extract(rows, config={"type": "HogQLAlertConfig", "evaluation": "any_row"})


def test_any_row_rejects_relative_conditions():
    with pytest.raises(AlertExtractionError, match="absolute value conditions"):
        _extract(
            [["US", 1]],
            columns=["country", "count"],
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            config={"type": "HogQLAlertConfig", "evaluation": "any_row"},
        )
