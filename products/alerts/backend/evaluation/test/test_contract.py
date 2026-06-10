from posthog.schema import AlertCondition, AlertConditionType

from products.alerts.backend.evaluation.contract import lookback_intervals_for


def test_absolute_value_needs_two_intervals():
    assert lookback_intervals_for(AlertCondition(type=AlertConditionType.ABSOLUTE_VALUE)) == 2


def test_relative_increase_needs_three_intervals():
    assert lookback_intervals_for(AlertCondition(type=AlertConditionType.RELATIVE_INCREASE)) == 3


def test_relative_decrease_needs_three_intervals():
    assert lookback_intervals_for(AlertCondition(type=AlertConditionType.RELATIVE_DECREASE)) == 3
