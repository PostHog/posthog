from collections.abc import Callable

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

# Aggregated (any-row) breach lists are capped so a wide violation doesn't flood the notification.
# The persisted structured detail uses the same cap.
MAX_BREACH_MESSAGES = 5


def _breach_messages(
    bounds: InsightsThresholdBounds,
    calculated_value: float,
    threshold_type: InsightThresholdType,
    condition_type: AlertConditionType,
    *,
    subject: str,
    framed: bool,
    include_series: bool = False,
    interval_type: IntervalType | None = None,
    series: str | None = None,
    is_current_interval: bool = False,
    unit: str = "",
    value_formatter: Callable[[float], str] | None = None,
) -> list[str]:
    is_percentage = threshold_type == InsightThresholdType.PERCENTAGE

    # PERCENTAGE thresholds render the relative-change ratio as their own % and take precedence.
    # Otherwise a trends ``value_formatter`` mirrors the insight's axis format (currency, prefix,
    # decimals). Falls back to raw value + ``unit`` (e.g. "%" for funnel conversion rates, which are
    # absolute 0–100 values) to keep the notification consistent with the configure-time UI.
    def _fmt(value: float) -> str:
        if is_percentage:
            return f"{value:.2%}"
        if value_formatter is not None:
            return value_formatter(value)
        return f"{value}{unit}"

    formatted_value = _fmt(calculated_value)

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
    # insights): just the subject — plus the series label when several series are in play
    # (any-row SQL alerts), since the reader needs to know which row breached.
    if framed:
        context = f" ({series}) for {'current' if is_current_interval else 'previous'} {interval_type or 'interval'}"
    elif include_series and series is not None:
        context = f" ({series})"
    else:
        context = ""

    if bounds.lower is not None and calculated_value < bounds.lower:
        return [
            f"{subject}{context} ({formatted_value}) {condition_text} less than lower threshold ({_fmt(bounds.lower)})"
        ]

    if bounds.upper is not None and calculated_value > bounds.upper:
        return [
            f"{subject}{context} ({formatted_value}) {condition_text} more than upper threshold ({_fmt(bounds.upper)})"
        ]

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
    all_breaches: list[str] = []
    breaching_rows: list[dict] = []
    first_breach_value: float | None = None
    for s in result.series:
        # A degenerate series (empty, or too short for the chosen anchor) can leave current_index
        # out of bounds — skip it rather than indexing, mirroring the "no previous point" skip below.
        if not 0 <= s.current_index < len(s.points):
            continue
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
            include_series=result.is_breakdown or result.include_series_label,
            interval_type=result.interval_type,
            series=s.label,
            is_current_interval=s.is_current_interval,
            unit=result.unit,
            value_formatter=result.value_formatter,
        )
        if breaches:
            if not result.aggregate_breaches:
                return AlertEvaluationResult(value=calculated, breaches=breaches)
            if first_breach_value is None:
                # Representative value = the first breaching row in result order; the full list
                # of breaching rows is carried by ``breaches`` and ``triggered_metadata``.
                first_breach_value = calculated
            all_breaches.extend(breaches)
            breaching_rows.append({"label": s.label, "value": calculated})

    if all_breaches:
        capped = all_breaches[:MAX_BREACH_MESSAGES]
        if len(all_breaches) > MAX_BREACH_MESSAGES:
            capped.append(f"...and {len(all_breaches) - MAX_BREACH_MESSAGES} more rows breach")
        # Persist which rows breached on the check record — notifications are transient, and the
        # row labels have no other durable source of truth.
        return AlertEvaluationResult(
            value=first_breach_value,
            breaches=capped,
            triggered_metadata={
                "breaching_rows": breaching_rows[:MAX_BREACH_MESSAGES],
                "breaching_row_count": len(breaching_rows),
            },
        )

    # No breach: an empty query result reports 0 regardless of breakdown (the metric is genuinely
    # zero — matching the original _is_empty_query_result); otherwise a non-breakdown query reports
    # its computed value and a breakdown has no single representative value, so it reports None.
    if result.empty_query_result:
        no_breach_value: float | None = 0
    else:
        no_breach_value = None if result.is_breakdown else calculated
    return AlertEvaluationResult(value=no_breach_value, breaches=[])
