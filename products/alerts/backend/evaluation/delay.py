from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from posthog.schema import IntervalType, NodeKind, TrendsQuery

from posthog.tasks.alerts.trends import _is_non_time_series_trend
from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS, AlertEvaluationResult
from posthog.utils import get_from_dict_or_attr

from products.alerts.backend.evaluation.contract import EvaluatedInterval, ExtractionResult


class DelayedEvaluationUnavailable(Exception):
    pass


def validate_evaluation_delay(query: object, config: object, delay: int) -> None:
    if isinstance(delay, bool) or not isinstance(delay, int) or not 0 <= delay <= 100:
        raise ValueError("Evaluation delay must be a whole number between 0 and 100 intervals.")
    if delay == 0:
        return
    if get_from_dict_or_attr(query, "kind") in WRAPPER_NODE_KINDS:
        query = get_from_dict_or_attr(query, "source")
    if get_from_dict_or_attr(query, "kind") != NodeKind.TRENDS_QUERY or _is_non_time_series_trend(
        TrendsQuery.model_validate(query)
    ):
        raise ValueError("Evaluation delay is only supported for time-series Trends insights.")
    if config is not None and not isinstance(config, dict):
        raise ValueError("Alert config must be a JSON object.")
    if (config or {}).get("check_ongoing_interval"):
        raise ValueError("Turn off Check ongoing period to use an evaluation delay.")


def apply_evaluation_delay(
    result: ExtractionResult, *, delay: int, minimum_points: int, timezone: str
) -> ExtractionResult:
    if delay == 0:
        return result
    selected_series = []
    evaluated_interval = None
    for series in result.series:
        index = series.current_index - delay
        if index + 1 < minimum_points:
            raise DelayedEvaluationUnavailable(
                f"Not enough completed intervals after the evaluation delay. At least {minimum_points} eligible "
                "intervals are required. Wait for more data or reduce the evaluation delay."
            )
        if any(point.value is None for point in series.points[index + 1 - minimum_points : index + 1]):
            raise DelayedEvaluationUnavailable(
                "The eligible intervals contain missing values. Wait for more data or check the insight."
            )
        start, end = series.points[index].date, series.points[index + 1].date
        if start is None or end is None:
            raise DelayedEvaluationUnavailable("The delayed interval has no dates. Check the insight and try again.")
        if result.interval_type == IntervalType.DAY:
            end = _day_bucket_end(start, end, timezone)
        evaluated_interval = EvaluatedInterval(start=start, end=end, timezone=timezone, delay=delay)
        selected_series.append(replace(series, points=series.points[: index + 1], current_index=index))
    if not selected_series:
        raise DelayedEvaluationUnavailable(
            "No completed intervals are available after the evaluation delay. Wait for more data or reduce the delay."
        )
    return replace(
        result, series=selected_series, evaluated_interval=evaluated_interval, framed=False, include_series_label=True
    )


def _day_bucket_end(start: str, next_start: str, timezone: str) -> str:
    # A daysOfWeek filter drops day buckets, so the next returned bucket can start days later.
    try:
        if date.fromisoformat(next_start[:10]) - date.fromisoformat(start[:10]) <= timedelta(days=1):
            return next_start
        if len(start) == 10:
            return (date.fromisoformat(start) + timedelta(days=1)).isoformat()
        moment = datetime.fromisoformat(start)
    except ValueError:
        return next_start
    if moment.tzinfo is not None:
        moment = moment.astimezone(ZoneInfo(timezone))
    return (moment + timedelta(days=1)).isoformat()


def describe_delayed_evaluation(result: AlertEvaluationResult, extraction: ExtractionResult) -> AlertEvaluationResult:
    interval = extraction.evaluated_interval
    if interval is None:
        return result
    context = f"Evaluated {interval.start} to {interval.end} ({interval.timezone}; delay: {interval.delay} intervals)."
    return replace(
        result,
        breaches=[f"{context} {breach}" for breach in result.breaches] if result.breaches else result.breaches,
        triggered_metadata={
            **(result.triggered_metadata or {}),
            "evaluation_delay_intervals": interval.delay,
            "evaluated_interval_start": interval.start,
            "evaluated_interval_end": interval.end,
            "evaluated_interval_timezone": interval.timezone,
        },
    )
