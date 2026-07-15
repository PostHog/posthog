from typing import Any

from posthog.schema import InsightThreshold, MetricsAlertConfig, MetricsQuery

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.event_usage import EventSource

from products.alerts.backend.evaluation.contract import (
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
    zero_sentinel_series,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight

_SUBJECT = "The metric value"


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
    ) -> list[ComparableSeries]:
        series: list[ComparableSeries] = []
        for row in results:
            if not isinstance(row, dict):
                continue
            raw_points = row.get("points") or []
            points = [SeriesPoint(date=point.get("time"), value=point.get("value")) for point in raw_points]
            if not points:
                continue
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
