from posthog.schema import (
    AlertCondition,
    AlertConditionType,
    InsightsThresholdBounds,
    InsightThreshold,
    InsightThresholdType,
    IntervalType,
)

from posthog.tasks.alerts.utils import AlertEvaluationResult

from products.alerts.backend.evaluation.contract import ExtractionResult


def _breach_messages(
    bounds: InsightsThresholdBounds,
    calculated_value: float,
    threshold_type: InsightThresholdType,
    condition_type: AlertConditionType,
    *,
    subject: str,
    framed: bool,
    interval_type: IntervalType | None = None,
    series: str | None = None,
    is_current_interval: bool = False,
) -> list[str]:
    is_percentage = threshold_type == InsightThresholdType.PERCENTAGE
    formatted_value = f"{calculated_value:.2%}" if is_percentage else calculated_value

    match condition_type:
        case AlertConditionType.ABSOLUTE_VALUE:
            condition_text = "is"
        case AlertConditionType.RELATIVE_INCREASE:
            condition_text = "increased"
        case AlertConditionType.RELATIVE_DECREASE:
            condition_text = "decreased"
        case _:
            raise ValueError(f"Unsupported alert condition type: {condition_type}")

    # Framed (time-series trends): "(label) for current/previous interval". Unframed (e.g. SQL
    # insights): just the subject, since there is no series label or interval to reference.
    context = (
        f" ({series}) for {'current' if is_current_interval else 'previous'} {interval_type or 'interval'}"
        if framed
        else ""
    )

    if bounds.lower is not None and calculated_value < bounds.lower:
        lower_value = f"{bounds.lower:.2%}" if is_percentage else bounds.lower
        return [f"{subject}{context} ({formatted_value}) {condition_text} less than lower threshold ({lower_value})"]

    if bounds.upper is not None and calculated_value > bounds.upper:
        upper_value = f"{bounds.upper:.2%}" if is_percentage else bounds.upper
        return [f"{subject}{context} ({formatted_value}) {condition_text} more than upper threshold ({upper_value})"]

    return []


def _relative_value(
    condition_type: AlertConditionType,
    threshold_type: InsightThresholdType,
    anchor: float,
    previous: float,
) -> float:
    """Compute the relative change between the anchor point and the one before it.

    Both increase and decrease divide by ``previous`` (the earlier interval); the sign of
    the numerator flips so a decrease is reported as a positive magnitude.
    """
    numerator = anchor - previous if condition_type == AlertConditionType.RELATIVE_INCREASE else previous - anchor

    if threshold_type == InsightThresholdType.ABSOLUTE:
        return numerator
    if threshold_type != InsightThresholdType.PERCENTAGE:
        raise ValueError(f"Neither relative nor absolute threshold configured for alert condition {condition_type}")
    if previous == 0 and anchor == 0:
        return 0
    if previous == 0:
        return float("inf")
    return numerator / previous


def evaluate_threshold(
    result: ExtractionResult,
    condition: AlertCondition,
    threshold: InsightThreshold | None,
) -> AlertEvaluationResult:
    """Compare an extractor's result against the threshold; breach if ANY series breaches.

    Kind-agnostic: every insight kind's extractor normalizes into an ``ExtractionResult`` and the
    completeness/ongoing-interval policy is already encoded in each series' ``current_index``.

    ``result.is_breakdown`` controls only the no-breach reported value: a breakdown query has no
    single representative value, so it reports ``None``, whereas a single-series query reports its
    computed value.
    """
    bounds = threshold.bounds if threshold else None
    if not threshold or not bounds:
        return AlertEvaluationResult(value=0, breaches=[])

    calculated: float | None = None
    for s in result.series:
        anchor = s.points[s.current_index].value
        if anchor is None:
            continue

        if condition.type == AlertConditionType.ABSOLUTE_VALUE:
            calculated = anchor
        else:
            previous = s.points[s.current_index - 1].value if s.current_index - 1 >= 0 else None
            if previous is None:
                continue
            calculated = _relative_value(condition.type, threshold.type, anchor, previous)

        breaches = _breach_messages(
            bounds,
            calculated,
            threshold.type,
            condition.type,
            subject=result.subject,
            framed=result.framed,
            interval_type=result.interval_type,
            series=s.label,
            is_current_interval=s.is_current_interval,
        )
        if breaches:
            return AlertEvaluationResult(value=calculated, breaches=breaches)

    # No breach: an empty query result reports 0 regardless of breakdown (the metric is genuinely
    # zero — matching the original _is_empty_query_result); otherwise a non-breakdown query reports
    # its computed value and a breakdown has no single representative value, so it reports None.
    if result.empty_query_result:
        no_breach_value: float | None = 0
    else:
        no_breach_value = None if result.is_breakdown else calculated
    return AlertEvaluationResult(value=no_breach_value, breaches=[])
