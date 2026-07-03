from typing import Any, cast

from posthog.schema import FunnelConversionMetric, FunnelsAlertConfig, FunnelsQuery, FunnelVizType

from products.alerts.backend.evaluation.contract import AlertExtractionError, ComparableSeries, SeriesPoint

# Funnel alerts evaluate a conversion-rate percentage (0–100): a steps funnel at the configured step,
# a trends funnel at the latest period. Other viz types (time-to-convert, flow) have no conversion-rate
# metric and aren't supported — see strategy_for_viz.
_CONVERSION_RATE_SUBJECT = "The funnel conversion rate"
_CONVERSION_RATE_UNIT = "%"


class FunnelVizStrategy:
    """Per-viz-type behavior for funnel alerts: how to validate the config and read the query result
    into a ``ComparableSeries`` the shared comparator can evaluate, plus the breach-message subject
    and value unit. Selected by ``funnelVizType`` via ``strategy_for_viz`` — the funnel analogue of
    the per-kind extractor registry in dispatcher.py. Adding a viz type = adding a subclass here.
    """

    subject: str
    unit: str
    # Whether relative (increase/decrease) conditions make sense: only for viz types that produce a
    # time series with a prior value to compare against. A single snapshot (steps) has none.
    supports_relative_conditions: bool = False

    def validate_config(self, funnels_query: FunnelsQuery, config: FunnelsAlertConfig) -> None:
        """Reject configs this viz type can't evaluate, at alert save time (raises ``ValueError``).
        Default: nothing to reject — only the steps funnel has a per-step config to range-check."""
        return None

    def to_series(self, result: Any, config: FunnelsAlertConfig) -> list[ComparableSeries]:
        """Normalize the funnel query result into one ``ComparableSeries`` per breakdown value."""
        raise NotImplementedError


class StepsFunnelStrategy(FunnelVizStrategy):
    """Steps funnel: a single conversion-rate snapshot at the configured step (one point per series)."""

    subject = _CONVERSION_RATE_SUBJECT
    unit = _CONVERSION_RATE_UNIT

    def validate_config(self, funnels_query: FunnelsQuery, config: FunnelsAlertConfig) -> None:
        step = config.funnel_step
        if step is not None:
            if step < 0:
                raise ValueError(f"funnel_step must be >= 0, got {step}")
            # Exclusion nodes live in funnelsFilter, not series, so the series count is the result step
            # count for a STEPS funnel — matching the extractor's eval-time range check.
            if step >= len(funnels_query.series):
                raise ValueError(f"funnel_step {step} is out of range (funnel has {len(funnels_query.series)} steps)")
        if config.metric == FunnelConversionMetric.CONVERSION_FROM_PREVIOUS and step == 0:
            raise ValueError(
                "conversion_from_previous is undefined at the first step; use conversion_from_start instead"
            )

    def to_series(self, result: Any, config: FunnelsAlertConfig) -> list[ComparableSeries]:
        # A steps funnel is a single snapshot: the condition is always absolute (enforced upstream) and
        # check_ongoing_interval has no meaning (there are no periods), so neither is read here.
        rows = _require_list(_current_period_only(result), "steps")
        if not rows:
            return _no_data_series()
        return [
            ComparableSeries(
                label=_label_for_breakdown(steps[0].get("breakdown_value") if steps else None),
                points=[SeriesPoint(date=None, value=_conversion_rate(steps, config))],
                current_index=0,
            )
            for steps in _steps_per_breakdown(rows)
        ]


class HistoricalTrendsFunnelStrategy(FunnelVizStrategy):
    """Historical-trend funnel: a time series of overall conversion rates. ``funnel_step``/``metric``
    don't apply (the trend is the whole-funnel rate set by funnelsFilter), so the default no-op
    ``validate_config`` is inherited. Being a time series, it supports relative conditions too."""

    subject = _CONVERSION_RATE_SUBJECT
    unit = _CONVERSION_RATE_UNIT
    supports_relative_conditions = True

    def to_series(self, result: Any, config: FunnelsAlertConfig) -> list[ComparableSeries]:
        series_dicts = _require_list(_current_period_only(result), "trends")
        # An empty list means no users entered the funnel in the window — benign "no data this
        # interval", not a misconfiguration — represent it so the comparator skips it.
        if not series_dicts:
            return _no_data_series()
        # By default evaluate the last *complete* period — the latest one is still in progress, so
        # anchoring there would read a partial rate (and, for relative, diff a partial against a complete
        # one). check_ongoing_interval opts into that in-progress period. The anchor is the same for
        # absolute and relative conditions; relative then diffs it against the period before it.
        anchor_current = bool(config.check_ongoing_interval)
        series: list[ComparableSeries] = []
        for entry in series_dicts:
            if not isinstance(entry, dict):
                raise AlertExtractionError(
                    f"Funnel trends series is malformed (expected an object, got {type(entry).__name__})."
                )
            data = entry.get("data") or []
            dates = entry.get("days") or [None] * len(data)
            points = [SeriesPoint(date=date, value=_numeric_or_none(value)) for date, value in zip(dates, data)]
            if not points:
                # No periods in range — represent as a single missing point so the comparator skips it.
                points = [SeriesPoint(date=None, value=None)]
            current_index = max(len(points) - 1 if anchor_current else len(points) - 2, 0)
            label = _label_for_breakdown(entry.get("breakdown_value"))
            series.append(ComparableSeries(label=label, points=points, current_index=current_index))
        return series


# Mirrors EXTRACTORS in dispatcher.py: one strategy per supported funnel viz type. A funnel with no
# explicit viz type defaults to STEPS (matching the schema default), resolved in strategy_for_viz.
FUNNEL_VIZ_STRATEGIES: dict[FunnelVizType, FunnelVizStrategy] = {
    FunnelVizType.STEPS: StepsFunnelStrategy(),
    FunnelVizType.TRENDS: HistoricalTrendsFunnelStrategy(),
}


def strategy_for_viz(viz: FunnelVizType | None) -> FunnelVizStrategy:
    # ValueError (not KeyError) so the API maps an unsupported viz to a 400 at save time.
    strategy = FUNNEL_VIZ_STRATEGIES.get(viz or FunnelVizType.STEPS)
    if strategy is None:
        raise ValueError(f"Funnel alerts aren't supported for the '{viz}' visualization.")
    return strategy


def _is_current_period_row(row: Any) -> bool:
    return not isinstance(row, dict) or row.get("compare_label") in (None, "current")


def _current_period_only(result: Any) -> Any:
    """Keep only current-period rows from a compare-enabled funnel result before normalizing.

    With compare-to-previous on, the funnel runner concatenates current + previous rows (each tagged
    ``compare_label``). Funnel alerts evaluate the current period; without this, a steps funnel's
    default last-row resolution or a trends series would mix periods. No-op when compare is off.

    For a breakdown steps funnel the runner emits the previous-period breakdowns as their own groups,
    which filter to empty — drop those, or an empty group would resolve ``funnel_step`` to -1 and raise.
    """
    if not isinstance(result, list):
        return result
    if result and isinstance(result[0], list):
        filtered = [[row for row in steps if _is_current_period_row(row)] for steps in result]
        return [steps for steps in filtered if steps]
    return [row for row in result if _is_current_period_row(row)]


def _no_data_series() -> list[ComparableSeries]:
    """The benign "no data this interval" result for an empty funnel query.

    An empty funnel result means no users entered the funnel in the window — a benign transient
    state, not a misconfiguration. Represented as a single missing point so the comparator skips it
    (NOT_FIRING, no error), rather than raising and surfacing a benign empty funnel to error tracking
    as if it were a crash.
    """
    return [ComparableSeries(label="conversion", points=[SeriesPoint(date=None, value=None)], current_index=0)]


def _require_list(result: Any, viz_label: str) -> list[Any]:
    """Normalize a funnel query result to a list, or fail loud on an unexpected shape.

    A genuinely unexpected shape (e.g. None from a swallowed query error) is a hard failure, not
    "no data" — raise ``AlertExtractionError`` so the alert auto-disables rather than silently
    reporting no data. An empty list passes through and the caller renders it as a benign no-data
    series.
    """
    if not isinstance(result, list):
        raise AlertExtractionError(
            f"Funnel {viz_label} alert query returned an unexpected result shape ({type(result).__name__})."
        )
    return result


def _steps_per_breakdown(result: list[Any]) -> list[list[dict[str, Any]]]:
    """Normalize a non-empty steps funnel result into a list of step-lists (one per breakdown value).

    A non-breakdown funnel returns ``list[step]``; a breakdown funnel returns ``list[list[step]]``.
    """
    if isinstance(result[0], list):
        return cast(list[list[dict[str, Any]]], result)
    return [cast(list[dict[str, Any]], result)]


def _label_for_breakdown(breakdown: Any) -> str:
    # Mirrors the frontend's `_breakdownLabel`.
    if breakdown is None:
        return "conversion"
    return ", ".join(str(v) for v in breakdown) if isinstance(breakdown, list) else str(breakdown)


def _numeric_or_none(value: Any) -> float | None:
    # Route a non-numeric metric to "no data this interval" (the comparator skips a None anchor)
    # rather than letting a type error surface as an internal crash.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _step_count(steps: list[dict[str, Any]], index: int) -> float:
    # Route a malformed step shape to the errored-alert path (like the SQL extractor's _numeric_cell)
    # rather than letting a raw KeyError/TypeError surface as an internal crash.
    step = steps[index]
    if not isinstance(step, dict):
        raise AlertExtractionError(f"Funnel step {index} is malformed (expected an object, got {type(step).__name__}).")
    count = step.get("count")
    if isinstance(count, bool) or not isinstance(count, int | float):
        raise AlertExtractionError(f"Funnel step {index} has a non-numeric count: {count!r}.")
    return count


def _conversion_rate(steps: list[dict[str, Any]], config: FunnelsAlertConfig) -> float:
    """Conversion rate (0–100) for the configured step and metric."""
    step_count = len(steps)
    step_index = config.funnel_step if config.funnel_step is not None else step_count - 1
    if step_index < 0 or step_index >= step_count:
        raise AlertExtractionError(f"funnel_step {step_index} is out of range (funnel has {step_count} steps).")

    if config.metric == FunnelConversionMetric.CONVERSION_FROM_PREVIOUS:
        if step_index == 0:
            raise AlertExtractionError(
                "conversion_from_previous is undefined at the first step (there is no prior step); "
                "use conversion_from_start instead."
            )
        base_index = step_index - 1
    else:
        base_index = 0

    base = _step_count(steps, base_index)
    if base == 0:
        return 0.0
    return _step_count(steps, step_index) / base * 100
