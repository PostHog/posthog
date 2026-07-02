from posthog.schema import AlertCondition, InsightThreshold, IntervalType, NodeKind

from posthog.api.services.query import ExecutionMode
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS, AlertEvaluationResult
from posthog.utils import get_from_dict_or_attr

from products.alerts.backend.evaluation.comparator import evaluate_threshold
from products.alerts.backend.evaluation.contract import DetectorExtractor, Extractor, execution_mode_for_alert
from products.alerts.backend.evaluation.detector import TrendsDetectorExtractor, evaluate_with_detector
from products.alerts.backend.evaluation.funnels import FunnelsExtractor
from products.alerts.backend.evaluation.hogql import HogQLDetectorExtractor, HogQLExtractor
from products.alerts.backend.evaluation.trends import TrendsExtractor
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight

# Each insight kind that supports threshold alerts maps to one extractor. The comparator is shared.
EXTRACTORS: dict[NodeKind, Extractor] = {
    NodeKind.TRENDS_QUERY: TrendsExtractor(),
    NodeKind.HOG_QL_QUERY: HogQLExtractor(),
    NodeKind.FUNNELS_QUERY: FunnelsExtractor(),
}

# The anomaly-detector path mirrors EXTRACTORS: one detector extractor per kind, scored by the shared
# evaluate_with_detector. Funnels stay threshold-only (no native time series to score). This is the
# single source of truth for both detector paths — alert checks call extract(), read-only simulation
# (simulate_detector_on_insight) calls simulate() — so adding a kind here makes it work in both.
DETECTOR_EXTRACTORS: dict[NodeKind, DetectorExtractor] = {
    NodeKind.TRENDS_QUERY: TrendsDetectorExtractor(),
    NodeKind.HOG_QL_QUERY: HogQLDetectorExtractor(),
}


def _resolve_execution_mode(alert: AlertConfiguration, kind: NodeKind, query: object) -> ExecutionMode:
    # Compute the cache/recompute decision once for every kind. Only time-axis kinds (trends/detector)
    # escalate to a fresh recompute on hourly buckets; SQL/funnels have no hourly axis, so for them
    # only the alert cadence (every-15-minutes) forces fresh.
    raw_interval = get_from_dict_or_attr(query, "interval") if kind == NodeKind.TRENDS_QUERY else None
    interval = IntervalType(raw_interval) if raw_interval is not None else None
    return execution_mode_for_alert(interval, high_frequency=alert.is_high_frequency_interval)


def check_detector_alert(alert: AlertConfiguration, insight: Insight, query: object) -> AlertEvaluationResult:
    """Route a detector (anomaly) alert to its kind's detector extractor, then score the series.

    Shared by the dispatcher and the detector tests. The registry lookup is the kind gate — an
    unsupported kind raises rather than silently falling through to the threshold path.
    """
    detector_config = alert.detector_config
    if not detector_config:
        raise ValueError("check_detector_alert requires detector_config — dispatcher invariant violated")
    kind = get_from_dict_or_attr(query, "kind")
    detector_extractor = DETECTOR_EXTRACTORS.get(kind)
    if detector_extractor is None:
        raise NotImplementedError(f"AlertCheckError: Detector alerts for {kind} are not supported yet")
    result = detector_extractor.extract(alert, insight, query, _resolve_execution_mode(alert, kind, query))
    return evaluate_with_detector(result, detector_config)


def check_alert_for_insight(alert: AlertConfiguration) -> AlertEvaluationResult:
    """Dispatch an alert to its insight-kind extractor, then run the shared comparator.

    If ``detector_config`` is set, routes through the anomaly-detector registry (one extractor per
    supported insight kind); each detector extractor shares the ``ComparableSeries`` contract, so the
    dispatch shape mirrors the threshold path. Otherwise the extractor normalizes the query result into an
    ``ExtractionResult`` and the comparator evaluates it against the threshold.
    """
    insight = alert.insight

    with upgrade_query(insight):
        query = insight.query
        kind = get_from_dict_or_attr(query, "kind")

        if kind in WRAPPER_NODE_KINDS:
            query = get_from_dict_or_attr(query, "source")
            kind = get_from_dict_or_attr(query, "kind")

        if alert.detector_config:
            return check_detector_alert(alert, insight, query)

        extractor = EXTRACTORS.get(kind)
        if extractor is None:
            raise NotImplementedError(f"AlertCheckError: Alerts for {kind} are not supported yet")

        # Short-circuit before the (potentially expensive) query: no bounds means nothing to breach.
        threshold = InsightThreshold.model_validate(alert.threshold.configuration) if alert.threshold else None
        if not threshold or not threshold.bounds:
            return AlertEvaluationResult(value=0, breaches=[])

        condition = AlertCondition.model_validate(alert.condition)
        result = extractor.extract(alert, insight, query, _resolve_execution_mode(alert, kind, query))
        return evaluate_threshold(result, condition, threshold)
