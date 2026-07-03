from typing import Any, Optional, cast
from zoneinfo import ZoneInfo

import numpy as np

from posthog.schema import TrendsAlertConfig, TrendsQuery

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team import Team
from posthog.models.user import User
from posthog.schema_migrations.upgrade_manager import upgrade_query

# Low-level scoring/extraction primitives still live in the legacy detector module.
from posthog.tasks.alerts.detector import (
    MAX_DETECTOR_BREAKDOWN_VALUES,
    _compute_min_samples_for_detector,
    _date_range_override_for_detector,
    _extract_sub_detector_scores,
    _prepare_series,
)
from posthog.tasks.alerts.detectors import get_detector
from posthog.tasks.alerts.trends import (
    TrendResult,
    _has_breakdown,
    _is_non_time_series_trend,
    _pick_series_result,
    query_excludes_incomplete_periods,
)
from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS, AlertEvaluationResult
from posthog.utils import get_from_dict_or_attr, relative_date_parse

from products.alerts.backend.evaluation.contract import (
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
    SimulationContext,
    execution_mode_for_alert,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight


def extract_detector_series(
    insight: Insight,
    team: Any,
    query: TrendsQuery,
    detector_config: dict[str, Any],
    execution_mode: ExecutionMode,
    *,
    series_index: int = 0,
    date_from: str | None = None,
    user: Optional[User] = None,
) -> ExtractionResult:
    """Run a trends insight over the detector's lookback window and normalize it into series.

    Each ``ComparableSeries`` carries the full (complete-interval) history the detector scores —
    the incomplete current interval is already dropped by ``_prepare_series``. Raises on a ``None``
    result (swallowed query error). A genuinely empty query result yields an empty series list with
    ``empty_query_result=True``; rows that exist but are too short to score are dropped, also leaving
    an empty series list, but with the flag False — the two cases evaluate to 0 and None respectively.
    """
    min_samples = _compute_min_samples_for_detector(detector_config) + 1
    is_non_time_series = _is_non_time_series_trend(query)
    drop_current = not query_excludes_incomplete_periods(query)
    has_breakdown = _has_breakdown(query)

    if is_non_time_series:
        filters_override = None
    elif date_from:
        # Use whichever goes further back: the caller's range or the detector minimum.
        min_date_from = _date_range_override_for_detector(query, min_samples)
        utc = ZoneInfo("UTC")
        user_dt = relative_date_parse(date_from, utc)
        min_dt = relative_date_parse(min_date_from["date_from"], utc) if min_date_from else None
        filters_override = min_date_from if (min_dt and min_dt < user_dt) else {"date_from": date_from}
    else:
        filters_override = _date_range_override_for_detector(query, min_samples)

    calculation_result = calculate_for_query_based_insight(
        insight, team=team, execution_mode=execution_mode, user=user, filters_override=filters_override
    )

    if calculation_result.result is None:
        raise RuntimeError(f"No results found for insight with id = {insight.id}")
    if not calculation_result.result:
        return ExtractionResult(
            series=[], is_breakdown=has_breakdown, interval_type=query.interval, empty_query_result=True
        )

    if has_breakdown:
        results = cast(list[TrendResult], calculation_result.result)[:MAX_DETECTOR_BREAKDOWN_VALUES]
    else:
        config = TrendsAlertConfig(type="TrendsAlertConfig", series_index=series_index)
        results = [_pick_series_result(config, calculation_result)]

    series: list[ComparableSeries] = []
    for result in results:
        prepared = _prepare_series(result, is_non_time_series, drop_current=drop_current)
        if prepared is None:
            continue
        points = [
            SeriesPoint(date=(prepared.dates[i] if i < len(prepared.dates) else None), value=float(value))
            for i, value in enumerate(prepared.data)
        ]
        # current_index is set for contract conformance but unread on this path: the detector scores
        # the whole series rather than comparing against a single anchor interval.
        series.append(ComparableSeries(label=prepared.label, points=points, current_index=len(points) - 1))

    return ExtractionResult(series=series, is_breakdown=has_breakdown, interval_type=query.interval)


def _triggered_dates(series: ComparableSeries, triggered_indices: list[int]) -> list[str]:
    """Map triggered indices to their date strings, skipping points that carry no date."""
    return [date for i in triggered_indices if i < len(series.points) and (date := series.points[i].date) is not None]


def _anomaly_breach(
    label: str, current_value: float, score: float | None, detector_type_str: str, suffix: str = ""
) -> str:
    score_str = f" (anomaly probability: {score:.0%})" if score is not None else ""
    return (
        f"Anomaly detected in {label}: value {current_value:.2f}{score_str} using {detector_type_str} detector{suffix}"
    )


def _format_sub_detector(sub_result: dict[str, Any]) -> str:
    """Render one ensemble sub-detector's score for the breach message suffix."""
    score = sub_result.get("score")
    score_pct = f"{score:.0%}" if score is not None else "n/a"
    fired = " [fired]" if sub_result.get("is_anomaly", False) else ""
    return f"{sub_result.get('type', 'unknown')}: {score_pct}{fired}"


def evaluate_with_detector(result: ExtractionResult, detector_config: dict[str, Any]) -> AlertEvaluationResult:
    """Score an extracted trends series with an anomaly detector (the non-threshold alert path).

    Breakdown alerts fire on the first anomalous breakdown value; non-breakdown alerts score the
    single selected series.
    """
    detector_type_str = detector_config.get("type", "zscore")
    interval_value = result.interval_type.value if result.interval_type else None

    if not result.series:
        # Empty query → the metric is genuinely 0; rows present but unscorable → uncomputed (None).
        value: float | None = 0 if result.empty_query_result else None
        return AlertEvaluationResult(value=value, breaches=[], interval=interval_value)

    if result.is_breakdown:
        for bd_index, s in enumerate(result.series):
            data = np.array([p.value for p in s.points])
            detection = get_detector(detector_config).detect(data)
            if detection.is_anomaly:
                current_value = float(data[-1])
                return AlertEvaluationResult(
                    value=current_value,
                    breaches=[_anomaly_breach(s.label, current_value, detection.score, detector_type_str)],
                    anomaly_scores=detection.all_scores or None,
                    triggered_points=detection.triggered_indices or None,
                    triggered_dates=_triggered_dates(s, detection.triggered_indices or []) or None,
                    interval=interval_value,
                    triggered_metadata={"series_index": bd_index},
                )
        return AlertEvaluationResult(value=None, breaches=[], interval=interval_value)

    s = result.series[0]
    data = np.array([p.value for p in s.points])
    detection = get_detector(detector_config).detect(data)

    breaches: list[str] = []
    if detection.is_anomaly:
        current_value = float(data[-1])
        suffix = ""
        if detector_type_str == "ensemble" and detection.metadata:
            sub_results = detection.metadata.get("sub_results", [])
            if sub_results:
                parts = [_format_sub_detector(sr) for sr in sub_results]
                suffix = f" | sub-detectors: {', '.join(parts)}"
        breaches.append(_anomaly_breach(s.label, current_value, detection.score, detector_type_str, suffix))

    return AlertEvaluationResult(
        value=float(data[-1]) if len(data) > 0 else None,
        breaches=breaches,
        anomaly_scores=detection.all_scores or None,
        triggered_points=detection.triggered_indices or None,
        triggered_dates=_triggered_dates(s, detection.triggered_indices or []) or None,
        interval=interval_value,
    )


class TrendsDetectorExtractor:
    """Detector-path extractor for trends insights. Conforms to the same ``Extractor`` protocol as
    the threshold ``TrendsExtractor`` and emits the same ``ComparableSeries`` — it only differs in
    fetching the detector's wider lookback window (the whole series is scored, not a single anchor).
    """

    def extract(
        self, alert: AlertConfiguration, insight: Insight, query: Any, execution_mode: ExecutionMode
    ) -> ExtractionResult:
        detector_config = alert.detector_config
        if not detector_config:
            raise ValueError("TrendsDetectorExtractor requires detector_config — dispatcher invariant violated")
        trends_query = TrendsQuery.model_validate(query)
        series_index = (alert.config or {}).get("series_index", 0)
        return extract_detector_series(
            insight,
            alert.team,
            trends_query,
            detector_config,
            execution_mode,
            series_index=series_index,
            user=alert.created_by,
        )

    def simulate(self, insight: Insight, query: object, ctx: SimulationContext) -> tuple[ExtractionResult, str | None]:
        trends_query = TrendsQuery.model_validate(query)
        # Simulation isn't cadence-bound, so high_frequency=False; the interval still forces fresh on HOUR.
        execution_mode = execution_mode_for_alert(trends_query.interval, high_frequency=False)
        result = extract_detector_series(
            insight,
            ctx.team,
            trends_query,
            ctx.detector_config,
            execution_mode,
            series_index=ctx.series_index,
            date_from=ctx.date_from,
            user=ctx.user,
        )
        interval_value = trends_query.interval.value if trends_query.interval else None
        return result, interval_value


def simulate_detector_on_insight(
    insight: Insight,
    team: Team,
    detector_config: dict[str, Any],
    series_index: int = 0,
    date_from: str | None = None,
    user: Optional[User] = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a detector over historical insight data for chart visualization. Read-only (no AlertCheck)."""
    if insight.query is None:
        raise ValueError("Insight has no valid query.")

    with upgrade_query(insight):
        query = insight.query

    kind = get_from_dict_or_attr(query, "kind")
    if kind in WRAPPER_NODE_KINDS:
        query = get_from_dict_or_attr(query, "source")
        kind = get_from_dict_or_attr(query, "kind")

    # Read-only simulation runs outside the alert-check activity, so tag its query directly.
    tag_queries(product=Product.PRODUCT_ANALYTICS, feature=Feature.ALERTING)
    detector_type_str = detector_config.get("type", "zscore")

    # Route through the same kind→extractor registry as the alert path (check_detector_alert), so
    # simulation and evaluation can't drift: a kind added to DETECTOR_EXTRACTORS is automatically
    # simulatable via its extractor's simulate(). The import is lazy because dispatcher imports this
    # module's extractor classes — importing the registry at module load would cycle.
    from products.alerts.backend.evaluation.dispatcher import (  # noqa: PLC0415 — breaks dispatcher↔detector import cycle
        DETECTOR_EXTRACTORS,
    )

    extractor = DETECTOR_EXTRACTORS.get(kind)
    if extractor is None:
        raise ValueError(f"Anomaly detection simulation isn't supported for {kind} insights")

    ctx = SimulationContext(
        team=team,
        detector_config=detector_config,
        user=user,
        series_index=series_index,
        date_from=date_from,
        config=config,
    )
    result, interval_value = extractor.simulate(insight, query, ctx)

    if not result.series:
        # Preserve the original, more specific diagnostics: a genuinely empty query vs rows that
        # exist but are all too short to score (per breakdown / single-series).
        if result.empty_query_result:
            raise ValueError("No results found for insight.")
        if result.is_breakdown:
            raise ValueError("No breakdown values had enough data points for simulation.")
        # Rows exist but the series is shorter than the detector's window — say so, rather than the
        # misleading "no data" (e.g. a 40-row SQL query against the default 90-point window).
        raise ValueError(
            "Not enough data points to score: the series is shorter than the detector's window size. "
            "Return more rows or reduce the window size."
        )

    if result.is_breakdown:
        breakdown_sims = [_sim_from_series(s, detector_config, detector_type_str) for s in result.series]
        return {
            "data": [],
            "dates": [],
            "scores": [],
            "triggered_indices": [],
            "triggered_dates": [],
            "interval": interval_value,
            "total_points": sum(sim["total_points"] for sim in breakdown_sims),
            "anomaly_count": sum(sim["anomaly_count"] for sim in breakdown_sims),
            "breakdown_results": breakdown_sims,
        }

    sim = _sim_from_series(result.series[0], detector_config, detector_type_str)
    sim.pop("label", None)
    return {**sim, "interval": interval_value}


def _sim_from_series(
    series: ComparableSeries, detector_config: dict[str, Any], detector_type_str: str
) -> dict[str, Any]:
    """Score a single extracted series with detect_batch and shape it for the simulation chart."""
    detection = get_detector(detector_config).detect_batch(np.array([p.value for p in series.points]))
    triggered = detection.triggered_indices or []
    scores = detection.all_scores if detection.all_scores else [None] * len(series.points)

    sim: dict[str, Any] = {
        "label": series.label,
        "data": [p.value for p in series.points],
        # Non-time-series points carry no date; emit [] (not [None]) to match the legacy shape and
        # satisfy the dates=ListField(child=CharField()) serializer.
        "dates": [p.date for p in series.points if p.date is not None],
        "scores": scores,
        "triggered_indices": triggered,
        "triggered_dates": _triggered_dates(series, triggered),
        "total_points": len(series.points),
        "anomaly_count": len(triggered),
    }
    sub_scores = _extract_sub_detector_scores(detector_type_str, detection)
    if sub_scores:
        sim["sub_detector_scores"] = sub_scores
    return sim
