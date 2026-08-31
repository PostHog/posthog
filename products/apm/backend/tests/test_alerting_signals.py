from parameterized import parameterized

from products.apm.backend.alerting.signals import (
    ApmSignalKind,
    SignalMeasurement,
    ThresholdOperator,
    evaluate_threshold,
)

SIGNAL_KINDS = [(kind.value, kind) for kind in ApmSignalKind]


@parameterized.expand(
    [
        # Boundary cases matter most: an alert whose comparison is off by one edge fires a
        # window early or late on every evaluation.
        ("above breached", ThresholdOperator.ABOVE, 101.0, True),
        ("above at threshold", ThresholdOperator.ABOVE, 100.0, False),
        ("above clear", ThresholdOperator.ABOVE, 99.0, False),
        ("below breached", ThresholdOperator.BELOW, 99.0, True),
        ("below at threshold", ThresholdOperator.BELOW, 100.0, False),
        ("below clear", ThresholdOperator.BELOW, 101.0, False),
    ]
)
def test_threshold_comparison(_name: str, operator: ThresholdOperator, value: float, breached: bool) -> None:
    measurement = SignalMeasurement(kind=ApmSignalKind.LOGS, value=value)

    check = evaluate_threshold(measurement, threshold=100.0, operator=operator)

    assert check.threshold_breached is breached
    assert check.is_inconclusive is False


@parameterized.expand(SIGNAL_KINDS)
def test_comparison_is_identical_across_signals(_name: str, kind: ApmSignalKind) -> None:
    # The point of one alert object over three signals is that "above 100" means the same
    # thing whichever signal produced the number. A per-signal special case would break that.
    breached = evaluate_threshold(
        SignalMeasurement(kind=kind, value=101.0), threshold=100.0, operator=ThresholdOperator.ABOVE
    )
    clear = evaluate_threshold(
        SignalMeasurement(kind=kind, value=99.0), threshold=100.0, operator=ThresholdOperator.ABOVE
    )

    assert breached.threshold_breached is True
    assert clear.threshold_breached is False


@parameterized.expand([(operator.value, operator) for operator in (ThresholdOperator.ABOVE, ThresholdOperator.BELOW)])
def test_absent_measurement_is_inconclusive_rather_than_zero(_name: str, operator: ThresholdOperator) -> None:
    # Treating "no data" as 0 would make every `below` alert fire through an ingestion gap,
    # which is the standing false-positive trap for volume-floor alerts. An absent value has
    # to leave state and the failure counter untouched instead.
    check = evaluate_threshold(
        SignalMeasurement(kind=ApmSignalKind.TRACES, value=None), threshold=100.0, operator=operator
    )

    assert check.is_inconclusive is True
    assert check.threshold_breached is False
    assert check.error_message is None
