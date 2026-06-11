from decimal import Decimal

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
from products.alerts.backend.evaluation.hogql import HogQLExtractor, _extract_trailing_column_values

CALC_PATH = "products.alerts.backend.evaluation.hogql.calculate_for_query_based_insight"


def _alert(condition_type=AlertConditionType.ABSOLUTE_VALUE):
    alert = MagicMock()
    alert.condition = {"type": condition_type}
    return alert


def _threshold(type_=InsightThresholdType.ABSOLUTE, lower=None, upper=None):
    return InsightThreshold(type=type_, bounds=InsightsThresholdBounds(lower=lower, upper=upper))


# ---- _extract_trailing_column_values (pure) ----


def test_extract_none_result_raises_runtime_error():
    # A None result means the query layer swallowed an error — raise (not AlertExtractionError) to
    # avoid a misfire, matching the trends extractor.
    with pytest.raises(RuntimeError, match="No results found"):
        _extract_trailing_column_values(None, _alert())


def test_extract_empty_list_raises_no_rows():
    with pytest.raises(AlertExtractionError, match="no rows"):
        _extract_trailing_column_values([], _alert())


def test_extract_non_list_shape_raises_distinct_error():
    # A non-list result (wrong shape) is distinct from an empty list (no data).
    with pytest.raises(AlertExtractionError, match="unexpected result shape"):
        _extract_trailing_column_values({"not": "a list"}, _alert())


def test_extract_multi_column_raises():
    with pytest.raises(AlertExtractionError, match="exactly one column"):
        _extract_trailing_column_values([[1, 2]], _alert())


def test_extract_non_numeric_raises():
    with pytest.raises(AlertExtractionError, match="numeric column"):
        _extract_trailing_column_values([["text"]], _alert())


def test_extract_bool_is_non_numeric():
    with pytest.raises(AlertExtractionError, match="numeric column"):
        _extract_trailing_column_values([[True]], _alert())


def test_extract_none_bucket_becomes_zero():
    assert _extract_trailing_column_values([[None]], _alert()) == [0.0]


def test_extract_returns_trailing_two_as_floats():
    assert _extract_trailing_column_values([[1], [2], [3]], _alert()) == [2.0, 3.0]


def test_extract_accepts_decimal_columns():
    # ClickHouse Decimal columns surface as decimal.Decimal — they are valid numeric values.
    assert _extract_trailing_column_values([[Decimal("41.5")], [Decimal("42.0")]], _alert()) == [41.5, 42.0]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_extract_rejects_non_finite(bad):
    with pytest.raises(AlertExtractionError, match="finite numeric value"):
        _extract_trailing_column_values([[bad]], _alert())


# ---- HogQLExtractor.extract (mocked calculation) ----


def _extract_with_rows(rows, condition_type=AlertConditionType.ABSOLUTE_VALUE):
    with patch(CALC_PATH) as calc:
        calc.return_value = MagicMock(result=rows)
        return HogQLExtractor().extract(_alert(condition_type), MagicMock(), MagicMock())


def test_extract_builds_unframed_single_series():
    result = _extract_with_rows([[10], [42]])
    assert result.framed is False and result.is_breakdown is False
    assert result.subject == "The SQL insight value"
    assert [p.value for p in result.series[0].points] == [10.0, 42.0]
    assert result.series[0].current_index == 1  # last row is the anchor


def test_absolute_alert_breaches_on_last_row():
    result = _extract_with_rows([[10], [200]])
    evaluation = evaluate_threshold(
        result, AlertCondition(type=AlertConditionType.ABSOLUTE_VALUE), _threshold(upper=100)
    )
    assert evaluation.value == 200.0
    assert evaluation.breaches[0] == "The SQL insight value (200.0) is more than upper threshold (100.0)"


def test_relative_alert_needs_two_rows():
    with pytest.raises(AlertExtractionError, match="at least two rows"):
        _extract_with_rows([[5]], condition_type=AlertConditionType.RELATIVE_INCREASE)
