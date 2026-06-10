from posthog.schema import AlertCondition, InsightThreshold, NodeKind, TrendsQuery

from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS, AlertEvaluationResult
from posthog.utils import get_from_dict_or_attr

from products.alerts.backend.evaluation.comparator import evaluate_threshold
from products.alerts.backend.evaluation.contract import Extractor
from products.alerts.backend.evaluation.detector import evaluate_with_detector, extract_detector_series
from products.alerts.backend.evaluation.trends import TrendsExtractor
from products.alerts.backend.models.alert import AlertConfiguration

# Each insight kind that supports alerts maps to one extractor. The comparator is shared.
EXTRACTORS: dict[NodeKind, Extractor] = {
    NodeKind.TRENDS_QUERY: TrendsExtractor(),
}


def check_alert_for_insight(alert: AlertConfiguration) -> AlertEvaluationResult:
    """Dispatch an alert to its insight-kind extractor, then run the shared comparator.

    If ``detector_config`` is set, uses the anomaly-detector abstraction (trends-only); it has its
    own extractor (wider window) but shares the ``ComparableSeries`` contract, so the dispatch shape
    mirrors the threshold path. Otherwise the extractor normalizes the query result into an
    ``ExtractionResult`` and the comparator evaluates it against the threshold.
    """
    insight = alert.insight

    with upgrade_query(insight):
        query = insight.query
        kind = get_from_dict_or_attr(query, "kind")

        if kind in WRAPPER_NODE_KINDS:
            query = get_from_dict_or_attr(query, "source")
            kind = get_from_dict_or_attr(query, "kind")

        if alert.detector_config and kind == NodeKind.TRENDS_QUERY:
            trends_query = TrendsQuery.model_validate(query)
            series_index = (alert.config or {}).get("series_index", 0)
            detector_result = extract_detector_series(
                insight, alert.team, trends_query, alert.detector_config, series_index=series_index
            )
            return evaluate_with_detector(detector_result, alert.detector_config)

        extractor = EXTRACTORS.get(kind)
        if extractor is None:
            raise NotImplementedError(f"AlertCheckError: Alerts for {kind} are not supported yet")

        # Short-circuit before the (potentially expensive) query: no bounds means nothing to breach.
        threshold = InsightThreshold.model_validate(alert.threshold.configuration) if alert.threshold else None
        if not threshold or not threshold.bounds:
            return AlertEvaluationResult(value=0, breaches=[])

        condition = AlertCondition.model_validate(alert.condition)
        result = extractor.extract(alert, insight, query)
        return evaluate_threshold(result, condition, threshold)
