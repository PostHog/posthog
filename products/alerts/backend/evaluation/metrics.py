import datetime as dt
from typing import Any

from django.utils import timezone

from posthog.schema import InsightThreshold, MetricsAlertConfig, MetricsQuery

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.event_usage import EventSource
from posthog.models.team import Team
from posthog.models.user import User

# Low-level detector sizing primitives, shared with the trends/SQL detector extractors.
from posthog.tasks.alerts.detector import MAX_DETECTOR_BREAKDOWN_VALUES, _compute_min_samples_for_detector

from products.alerts.backend.evaluation.absence import absent_trailing_buckets
from products.alerts.backend.evaluation.contract import (
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
    SimulationContext,
    zero_sentinel_series,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.models import Insight

_SUBJECT = "The metric value"


def _series_points(row: dict[str, Any]) -> list[SeriesPoint]:
    return [SeriesPoint(date=point.get("time"), value=point.get("value")) for point in (row.get("points") or [])]


def _series_label(row: dict[str, Any]) -> str:
    name = row.get("metricName") or row.get("clause") or "metric"
    labels = row.get("labels") or {}
    if labels:
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(labels.items()))
        return f"{name} {{{rendered}}}"
    return str(name)


class MetricsExtractor:
    """Execute a metrics insight and normalize the result into ``ComparableSeries``.

    Every series the query returns is evaluated (group-by label-sets, multiple clauses, or the
    formula series) and the alert fires if any breaches — there is no series picker. The bucket
    grid is the union of observed buckets (zero-filled), so the anchor is positional: the last
    observed bucket with ``check_ongoing_interval``, otherwise the one before it, which skips the
    possibly still-accumulating trailing bucket.

    That grid only spans buckets that had samples, so a metric that stops being emitted ends its
    series at the last healthy value rather than at now. Left alone the anchor would keep reading
    that value and the alert would go quiet exactly when the emitter died, so closed buckets the
    series never reported are carried as explicit zeroes — the same reading a metric that never
    reported at all already gets from ``zero_sentinel_series``. Zero (rather than a gap) is what
    makes a lower bound fire on a dead metric while leaving an upper bound alone.
    """

    def extract(
        self, alert: AlertConfiguration, insight: Insight, query: Any, execution_mode: ExecutionMode
    ) -> ExtractionResult:
        MetricsQuery.model_validate(query)
        if not (alert.config and alert.config.get("type") == "MetricsAlertConfig"):
            raise ValueError(f"Unsupported alert config type: {alert.config}")
        config = MetricsAlertConfig.model_validate(alert.config)
        # Dispatcher short-circuits when threshold/bounds are missing, so both are present here.
        # Config/condition compatibility (e.g. check_ongoing_interval needs an upper bound) is
        # _validate_metrics_alert_config's job — enforced at save time and re-run by prepare_alert
        # before every check — so it isn't re-checked here.
        if alert.threshold is None:
            raise ValueError("MetricsExtractor requires a threshold — dispatcher invariant violated")
        threshold = InsightThreshold.model_validate(alert.threshold.configuration)
        if threshold.bounds is None:
            raise ValueError("MetricsExtractor requires threshold bounds — dispatcher invariant violated")

        check_ongoing_interval = bool(config.check_ongoing_interval)

        calculation_result = calculate_for_query_based_insight(
            insight,
            team=alert.team,
            execution_mode=execution_mode,
            # Scheduled alert check (no request user); attribute the read to the alert owner.
            user=alert.created_by,
            analytics_props={"source": EventSource.ALERT},
        )
        if calculation_result.result is None:
            raise RuntimeError(f"No results found for insight with alert id = {alert.id}")

        series = self._to_series(
            calculation_result.result,
            anchor_last_point=check_ongoing_interval,
            is_current_interval=check_ongoing_interval,
            # Judge absence as of when the result was computed, not wall clock: a cached
            # result knows nothing about buckets that closed after it ran, and treating
            # those as unreported would invent a breach out of cache age alone.
            fresh_as_of=calculation_result.last_refresh or timezone.now(),
        )
        if not series:
            # No observed buckets at all: the metric is genuinely absent, evaluated as 0 so a
            # lower-bound alert on a dead metric still fires.
            return ExtractionResult(
                series=[zero_sentinel_series()],
                subject=_SUBJECT,
                empty_query_result=True,
            )

        return ExtractionResult(
            series=series,
            is_breakdown=len(series) > 1,
            subject=_SUBJECT,
        )

    def _to_series(
        self,
        results: list[Any],
        *,
        anchor_last_point: bool,
        is_current_interval: bool,
        fresh_as_of: dt.datetime,
    ) -> list[ComparableSeries]:
        series: list[ComparableSeries] = []
        for row in results:
            if not isinstance(row, dict):
                continue
            points = _series_points(row)
            if not points:
                continue
            absent = absent_trailing_buckets([point.date for point in points if point.date], fresh_as_of)
            points.extend(SeriesPoint(date=bucket, value=0.0) for bucket in absent)
            # Anchor on the last observed bucket (ongoing mode) or the one before it. A single-point
            # series anchors on its only point; relative conditions then skip it (no previous point).
            current_index = len(points) - 1 if anchor_last_point else max(0, len(points) - 2)
            series.append(
                ComparableSeries(
                    label=_series_label(row),
                    points=points,
                    current_index=current_index,
                    is_current_interval=is_current_interval,
                )
            )
        return series


class MetricsDetectorExtractor:
    """Normalize a metrics insight into full series for the anomaly detectors.

    Reads the same result shape as ``MetricsExtractor`` but keeps the whole history
    instead of an anchor, because the detector scores every point rather than comparing
    one bucket against a bound.

    History depth comes from the insight's own date range and interval. The metrics
    runner targets a fixed bucket count, so widening the range alone coarsens the
    buckets rather than adding samples — pin a finer ``interval`` on the insight to give
    a wide detector window more to work with. A series shorter than the detector needs
    is dropped, which the shared scorer reports as uncomputed rather than as "normal".

    Absence padding deliberately does not apply here. Carrying a dead emitter's missed
    buckets as zeroes (what ``MetricsExtractor`` does, so a lower bound still fires)
    would read to a detector as a dramatic anomaly. Absence stays a threshold concern
    with threshold semantics.
    """

    def extract(
        self, alert: AlertConfiguration, insight: Insight, query: Any, execution_mode: ExecutionMode
    ) -> ExtractionResult:
        MetricsQuery.model_validate(query)
        if not alert.detector_config:
            raise ValueError("MetricsDetectorExtractor requires detector_config — dispatcher invariant violated")
        return self._extract(
            insight,
            team=alert.team,
            user=alert.created_by,
            detector_config=alert.detector_config,
            execution_mode=execution_mode,
        )

    def simulate(self, insight: Insight, query: object, ctx: SimulationContext) -> tuple[ExtractionResult, str | None]:
        MetricsQuery.model_validate(query)
        result = self._extract(
            insight,
            team=ctx.team,
            user=ctx.user,
            detector_config=ctx.detector_config,
            # Read-only preview: a recent cached result is fine and keeps the editor snappy.
            execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        )
        # The metrics runner resolves its own bucket size and doesn't report it back, so the
        # chart frames itself from the point timestamps instead of an interval name.
        return result, None

    def _extract(
        self,
        insight: Insight,
        *,
        team: Team,
        user: User | None,
        detector_config: dict[str, Any],
        execution_mode: ExecutionMode,
    ) -> ExtractionResult:
        calculation_result = calculate_for_query_based_insight(
            insight,
            team=team,
            execution_mode=execution_mode,
            user=user,
            analytics_props={"source": EventSource.ALERT},
        )
        if calculation_result.result is None:
            raise RuntimeError(f"No results found for insight with id = {insight.id}")

        rows = [row for row in calculation_result.result if isinstance(row, dict)]
        # A metrics query with no matching buckets still returns one placeholder series with an
        # empty point list, so "no rows" is not the only shape an empty result takes.
        if not any(row.get("points") for row in rows):
            return ExtractionResult(series=[], subject=_SUBJECT, empty_query_result=True)

        min_points = _compute_min_samples_for_detector(detector_config) + 1
        series: list[ComparableSeries] = []
        for row in rows[:MAX_DETECTOR_BREAKDOWN_VALUES]:
            points = _series_points(row)
            if len(points) < min_points:
                continue
            # current_index is set for contract conformance but unread on this path: the detector
            # scores the whole series rather than comparing against a single anchor bucket.
            series.append(ComparableSeries(label=_series_label(row), points=points, current_index=len(points) - 1))

        return ExtractionResult(series=series, is_breakdown=len(series) > 1, subject=_SUBJECT)
