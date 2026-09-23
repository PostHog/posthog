from collections.abc import Callable
from typing import Any, Optional, cast
from zoneinfo import ZoneInfo

import numpy as np

from posthog.schema import DetectorType, TrendsAlertConfig, TrendsQuery

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User
from posthog.schema_migrations.upgrade_manager import upgrade_insight

# Low-level scoring/extraction primitives still live in the legacy detector module.
from posthog.tasks.alerts.detector import (
    MAX_DETECTOR_BREAKDOWN_VALUES,
    _compute_min_samples_for_detector,
    _date_range_override_for_detector,
    _extract_sub_detector_scores,
    _prepare_series,
)
from posthog.tasks.alerts.detectors import DetectionResult, get_detector
from posthog.tasks.alerts.metric_definition import MetricDateRange, describe_metric_definition
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
    AlertExtractionError,
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
    SimulationContext,
    execution_mode_for_alert,
)
from products.alerts.backend.judge import (
    JudgeAttribution,
    LLMDetectorMisconfiguredError,
    SeriesContext,
    SeriesJudge,
    SeriesJudgment,
)
from products.alerts.backend.judge.llm import LLMSeriesJudge, prompt_window
from products.alerts.backend.llm_detector_limits import is_llm_detector_config
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.models import Insight


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
    already_complete = query_excludes_incomplete_periods(query)
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
        prepared = _prepare_series(result, is_non_time_series, drop_current=not already_complete)
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


def _metric_description(
    insight: Insight | None,
    series_index: int,
    effective_date_range: MetricDateRange | None = None,
    alert_config: dict[str, Any] | None = None,
) -> str:
    """Render the insight's query definition once per check, not once per breakdown value."""
    query = insight.query if insight is not None else None
    if not query:
        return ""
    return describe_metric_definition(
        query, series_index=series_index, effective_date_range=effective_date_range, alert_config=alert_config
    )


def _effective_date_range(result: ExtractionResult, detector_config: dict[str, Any]) -> MetricDateRange | None:
    """First and last date of the points the detector scores.

    Extraction widens the insight's saved range when the detector needs more buckets than it
    holds, so the saved range would describe a shorter span than the points beside it. The AI
    judge is shown only its trailing window, so its description covers that window alone.
    """
    shown = prompt_window(detector_config) if is_llm_detector_config(detector_config) else None
    for series in result.series:
        dates = [point.date for point in series.points if point.date]
        if shown is not None:
            dates = dates[-shown:]
        if dates:
            return MetricDateRange(start=dates[0], end=dates[-1])
    return None


def _series_context(
    series: ComparableSeries,
    detector_config: dict[str, Any],
    *,
    insight: Insight | None,
    interval: str | None,
    metric_description: str,
) -> SeriesContext:
    """What the judge reads about the series that the values array cannot carry."""
    return SeriesContext(
        dates=tuple(point.date for point in series.points),
        interval=interval,
        series_label=series.label,
        metric_description=metric_description,
        insight_name=(insight.name or "") if insight is not None else "",
        instructions=str(detector_config.get("instructions") or ""),
    )


def _judge_attribution(
    *, team: Team | None, user: User | None, evaluation_id: str | None, is_agent_billable: bool
) -> JudgeAttribution:
    """Who the judge's charged call runs as. Refused loudly when there is no one to attribute it to."""
    if team is None or user is None:
        raise LLMDetectorMisconfiguredError(
            "The AI detector needs a project and a user to attribute its model calls to. This "
            "alert has neither, which happens when the person who created it was deleted. "
            "Recreate the alert to fix it."
        )
    return JudgeAttribution(team=team, user=user, evaluation_id=evaluation_id, is_agent_billable=is_agent_billable)


def _series_judge(detector_config: dict[str, Any]) -> SeriesJudge:
    """The judge for a config whose type is not a registry detector. Only the AI judge today."""
    return LLMSeriesJudge(detector_config)


@frozen
class _ScoredSeries:
    """One series after the detector or judge has scored it, reduced to what the alert reads."""

    data: np.ndarray
    # None when nothing scored the series: the judge had too few points to ask the model.
    detection: DetectionResult | None
    # The slice of the score worth persisting on the check. A judgment's verdict fields; empty
    # for a statistical detector, whose metadata is fit state (means, thresholds) that nothing
    # downstream reads.
    persisted_metadata: dict[str, Any]
    breach_suffix: str


def _detection_from_judgment(judgment: SeriesJudgment | None) -> DetectionResult | None:
    """The judgment on the shape the rest of the evaluation reads. None is a series too short to judge."""
    if judgment is None:
        return None
    return DetectionResult(
        is_anomaly=judgment.fires,
        score=judgment.score,
        triggered_indices=list(judgment.triggered_indices),
        all_scores=list(judgment.all_scores),
    )


def _format_sub_detector(sub_result: dict[str, Any]) -> str:
    """Render one ensemble sub-detector's score for the breach message suffix."""
    score = sub_result.get("score")
    score_pct = f"{score:.0%}" if score is not None else "n/a"
    fired = " [fired]" if sub_result.get("is_anomaly", False) else ""
    return f"{sub_result.get('type', 'unknown')}: {score_pct}{fired}"


def _ensemble_suffix(detection: DetectionResult) -> str:
    sub_results = (detection.metadata or {}).get("sub_results", [])
    if not sub_results:
        return ""
    return f" | sub-detectors: {', '.join(_format_sub_detector(sr) for sr in sub_results)}"


def _score_series(
    series: ComparableSeries,
    detector_config: dict[str, Any],
    *,
    every_point: bool,
    series_context: SeriesContext,
    attribution: Callable[[], JudgeAttribution],
) -> _ScoredSeries:
    """Score one series with whatever its config names: a registry detector, or the AI judge.

    ``attribution`` is resolved only on the judge path, so an alert with no creator still
    evaluates on a statistical detector and only fails when a charged call would need someone
    to run as.
    """
    data = np.array([p.value for p in series.points])
    detector_type_str = detector_config.get("type", "zscore")
    if detector_type_str == DetectorType.LLM.value:
        judge = _series_judge(detector_config)
        judge_method = judge.judge_every_point if every_point else judge.judge_latest
        judgment = judge_method(data, series=series_context, attribution=attribution())
        rationale = judgment.rationale.strip() if judgment is not None else ""
        return _ScoredSeries(
            data=data,
            detection=_detection_from_judgment(judgment),
            persisted_metadata=judgment.persisted_metadata() if judgment is not None else {},
            breach_suffix=f". {rationale}" if rationale else "",
        )
    detector = get_detector(detector_config)
    detection = detector.detect_batch(data) if every_point else detector.detect(data)
    return _ScoredSeries(
        data=data,
        detection=detection,
        persisted_metadata={},
        breach_suffix=_ensemble_suffix(detection) if detector_type_str == "ensemble" else "",
    )


# The breach message a person reads names the detector. Every statistical type is already
# a recognizable name; "llm" is not something the alert editor ever calls it.
_DETECTOR_DISPLAY_NAMES = {DetectorType.LLM.value: "AI"}


def _anomaly_breach(label: str, scored: _ScoredSeries, detector_type_str: str) -> str:
    current_value = float(scored.data[-1])
    score = scored.detection.score if scored.detection is not None else None
    # The model's number is its own stated confidence, not a calibrated probability, so
    # the message must not present it as one.
    score_label = "model confidence" if detector_type_str == DetectorType.LLM.value else "anomaly probability"
    score_str = f" ({score_label}: {score:.0%})" if score is not None else ""
    name = _DETECTOR_DISPLAY_NAMES.get(detector_type_str, detector_type_str)
    return (
        f"Anomaly detected in {label}: value {current_value:.2f}{score_str} using {name} detector{scored.breach_suffix}"
    )


def evaluate_with_detector(
    result: ExtractionResult,
    detector_config: dict[str, Any],
    *,
    insight: Insight | None = None,
    alert: AlertConfiguration | None = None,
    evaluation_id: str | None = None,
) -> AlertEvaluationResult:
    """Score an extracted trends series with an anomaly detector (the non-threshold alert path).

    Breakdown alerts fire on the first anomalous breakdown value; non-breakdown alerts score the
    single selected series. ``insight`` and ``alert`` supply what the AI judge reads about the
    series and who its call runs as; the statistical detectors score identically without them.
    """
    detector_type_str = detector_config.get("type", "zscore")
    if result.is_breakdown and detector_type_str == DetectorType.LLM.value:
        raise AlertExtractionError("The AI detector does not support breakdown insights yet.")
    interval_value = result.interval_type.value if result.interval_type else None
    alert_config = (alert.config if alert is not None else None) or {}
    series_index = alert_config.get("series_index", 0)

    if not result.series:
        # Empty query → the metric is genuinely 0; rows present but unscorable → uncomputed (None).
        value: float | None = 0 if result.empty_query_result else None
        return AlertEvaluationResult(value=value, breaches=[], interval=interval_value)

    metric_description = _metric_description(
        insight, series_index, _effective_date_range(result, detector_config), alert_config
    )

    def score(series: ComparableSeries) -> _ScoredSeries:
        return _score_series(
            series,
            detector_config,
            every_point=False,
            series_context=_series_context(
                series, detector_config, insight=insight, interval=interval_value, metric_description=metric_description
            ),
            attribution=lambda: _judge_attribution(
                team=insight.team if insight is not None else None,
                user=alert.created_by if alert is not None else None,
                evaluation_id=evaluation_id,
                is_agent_billable=True,
            ),
        )

    if result.is_breakdown:
        for bd_index, s in enumerate(result.series):
            scored = score(s)
            if scored.detection is not None and scored.detection.is_anomaly:
                return AlertEvaluationResult(
                    value=float(scored.data[-1]),
                    breaches=[_anomaly_breach(s.label, scored, detector_type_str)],
                    anomaly_scores=scored.detection.all_scores or None,
                    triggered_points=scored.detection.triggered_indices or None,
                    triggered_dates=_triggered_dates(s, scored.detection.triggered_indices or []) or None,
                    interval=interval_value,
                    triggered_metadata={
                        **_check_provenance(insight, bd_index, detector_type_str),
                        **scored.persisted_metadata,
                    },
                )
        return AlertEvaluationResult(value=None, breaches=[], interval=interval_value)

    s = result.series[0]
    scored = score(s)
    if scored.detection is None:
        # Nothing judged the series, so the check is uncomputed rather than a healthy value
        # that never reached the model.
        return AlertEvaluationResult(value=None, breaches=[], interval=interval_value)

    breaches: list[str] = []
    if scored.detection.is_anomaly:
        breaches.append(_anomaly_breach(s.label, scored, detector_type_str))

    return AlertEvaluationResult(
        value=float(scored.data[-1]) if len(scored.data) > 0 else None,
        breaches=breaches,
        anomaly_scores=scored.detection.all_scores or None,
        triggered_points=scored.detection.triggered_indices or None,
        triggered_dates=_triggered_dates(s, scored.detection.triggered_indices or []) or None,
        interval=interval_value,
        triggered_metadata={**_check_provenance(insight, series_index, detector_type_str), **scored.persisted_metadata},
    )


def _check_provenance(insight: Insight | None, series_index: int, detector_type: str) -> dict[str, Any]:
    # Kept so an investigation that starts after the alert is edited still reads the check the
    # way it was produced. Statistical fit state stays off: a person and the firing event read this.
    provenance: dict[str, Any] = {"detector_type": detector_type, "series_index": series_index}
    if insight is not None:
        provenance["insight_id"] = insight.id
    return provenance


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
    *,
    score: bool = True,
    is_agent_billable: bool = True,
) -> dict[str, Any]:
    """Run a detector over historical insight data for chart visualization. Read-only (no AlertCheck).

    ``score=False`` returns the extracted series with no scores: for a caller that only wants
    the points, such as the investigation agent's chart, and must not pay for a model call.
    """
    if insight.query is None:
        raise ValueError("Insight has no valid query.")

    with upgrade_insight(insight):
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

    sim_context = _SimulationSeriesContext(
        insight=insight,
        interval=interval_value,
        metric_description=_metric_description(
            insight, series_index, _effective_date_range(result, detector_config), config
        ),
        user=user,
        score=score,
        is_agent_billable=is_agent_billable,
    )

    if result.is_breakdown:
        if detector_type_str == DetectorType.LLM.value:
            # One model call per breakdown value is the cost profile the saved-alert path
            # refuses; the preview must refuse it before the first call, not after the last.
            raise ValueError("The AI detector does not support breakdown insights yet.")
        breakdown_sims = [_sim_from_series(s, detector_config, detector_type_str, sim_context) for s in result.series]
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

    sim = _sim_from_series(result.series[0], detector_config, detector_type_str, sim_context)
    sim.pop("label", None)
    return {**sim, "interval": interval_value}


@frozen
class _SimulationSeriesContext:
    """The alert-less inputs a simulated series needs for the judge.

    A simulation runs outside any alert, so the user who asked for the preview is passed
    explicitly rather than read off ``alert.created_by``.
    """

    insight: Insight
    interval: str | None
    metric_description: str
    user: User | None
    score: bool = True
    is_agent_billable: bool = True


def _sim_from_series(
    series: ComparableSeries,
    detector_config: dict[str, Any],
    detector_type_str: str,
    sim_context: _SimulationSeriesContext,
) -> dict[str, Any]:
    """Score a single extracted series over every point and shape it for the simulation chart."""
    if sim_context.score:
        detection = _score_series(
            series,
            detector_config,
            every_point=True,
            series_context=_series_context(
                series,
                detector_config,
                insight=sim_context.insight,
                interval=sim_context.interval,
                metric_description=sim_context.metric_description,
            ),
            attribution=lambda: _judge_attribution(
                team=sim_context.insight.team,
                user=sim_context.user,
                evaluation_id=None,
                is_agent_billable=sim_context.is_agent_billable,
            ),
        ).detection
    else:
        detection = None
    if detection is None:
        detection = DetectionResult(is_anomaly=False)
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
