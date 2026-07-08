import pytest

from posthog.schema import AlertCondition, AlertConditionType

from products.alerts.backend.evaluation.contract import lookback_intervals_for


@pytest.mark.parametrize(
    "condition_type,expected_intervals",
    [
        (AlertConditionType.ABSOLUTE_VALUE, 2),
        (AlertConditionType.RELATIVE_INCREASE, 3),
        (AlertConditionType.RELATIVE_DECREASE, 3),
    ],
)
def test_lookback_intervals_for(condition_type, expected_intervals):
    assert lookback_intervals_for(AlertCondition(type=condition_type)) == expected_intervals
