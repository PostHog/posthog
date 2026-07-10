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

    def to_series(self, result: Any, config: FunnelsAlertConfig, *, already_complete: bool) -> list[ComparableSeries]:
        """Normalize the funnel query result into one ``ComparableSeries`` per breakdown value.

        ``already_complete`` is true when the query clips the ongoing interval
        (DateRange.excludeIncompletePeriods), so the trailing point is a complete period."""
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

    def to_series(self, result: Any, config: FunnelsAlertConfig, *, already_complete: bool) -> list[ComparableSeries]:
        # A steps funnel is a single snapshot: the condition is always absolute (enforced upstream) and
        # check_ongoing_interval/already_complete have no meaning (there are no periods).
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

    def to_series(self, result: Any, config: FunnelsAlertConfig, *, already_complete: bool) -> list[ComparableSeries]:
        # The clip removes the ongoing interval from the results, so an alert asking to check it can
        # never do what it says: reject the conflicting configuration instead of silently degrading.
        if config.check_ongoing_interval and already_complete:
            raise AlertExtractionError(
                "check_ongoing_interval is not supported when the insight excludes incomplete periods "
                "(DateRange.excludeIncompletePeriods): the ongoing interval is clipped from the query results."
            )
        series_dicts = _require_list(_current_period_only(result), "trends")
        # Empty = no one entered the funnel: benign, not a misconfig.
        if not series_dicts:
            return _no_data_series()
        # By default evaluate the last *complete* period — the latest one is still in progress, so
        # anchoring there would read a partial rate (and, for relative, diff a partial against a complete
        # one). check_ongoing_interval opts into that in-progress period; on a clipped query
        # (already_complete) the last period is complete, so it is the one to evaluate. The anchor is
        # the same for absolute and relative conditions; relative then diffs it against the period
        # before it.
        anchor_last = bool(config.check_ongoing_interval) or already_complete
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
            current_index = max(len(points) - 1 if anchor_last else len(points) - 2, 0)
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
    # A missing anchor value the comparator skips (NOT_FIRING, no error), so a benign empty funnel
    # isn't reported to error tracking as a crash.
    return [ComparableSeries(label="conversion", points=[SeriesPoint(date=None, value=None)], current_index=0)]


def _require_list(result: Any, viz_label: str) -> list[Any]:
    # A non-list (e.g. None from a swallowed query error) is a real failure, not "no data" — raise so
    # the alert auto-disables. An empty list is left for the caller to treat as benign no-data.
    if not isinstance(result, list):
        raise AlertExtractionError(
            f"Funnel {viz_label} alert query returned an unexpected result shape ({type(result).__name__})."
        )
    return result


def _steps_per_breakdown(result: list[Any]) -> list[list[dict[str, Any]]]:
    # The runner returns ``list[step]`` without a breakdown and ``list[list[step]]`` with one; unify.
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
