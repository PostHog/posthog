from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import AlertCondition, InsightThreshold, IntervalType, NodeKind

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.services.query import ExecutionMode
from posthog.dataclasses import frozen
from posthog.errors import CH_TRANSIENT_ERRORS, ExposedCHQueryError
from posthog.hogql_queries.validation.validate_query import rule_violation_message
from posthog.models.team import Team
from posthog.schema_migrations.upgrade_manager import upgrade_insight
from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS, AlertEvaluationResult
from posthog.utils import get_from_dict_or_attr, relative_date_parse_with_delta_mapping

from products.alerts.backend.evaluation.comparator import evaluate_threshold
from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ComparableSeries,
    DetectorExtractor,
    ExtractionResult,
    Extractor,
    cache_age_seconds_for_alert,
    execution_mode_for_alert,
)
from products.alerts.backend.evaluation.delay import (
    DelayedEvaluationUnavailable,
    describe_delayed_evaluation,
    validate_evaluation_delay,
)
from products.alerts.backend.evaluation.detector import TrendsDetectorExtractor, evaluate_with_detector
from products.alerts.backend.evaluation.funnels import FunnelsExtractor
from products.alerts.backend.evaluation.hogql import HogQLDetectorExtractor, HogQLExtractor
from products.alerts.backend.evaluation.metrics import MetricsExtractor
from products.alerts.backend.evaluation.trends import TrendsExtractor
from products.alerts.backend.judge.contract import LLMDetectorUnavailableError
from products.alerts.backend.llm_detector_limits import is_llm_detector_config
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.models import Insight

# Each insight kind that supports threshold alerts maps to one extractor. The comparator is shared.
EXTRACTORS: dict[NodeKind, Extractor] = {
    NodeKind.TRENDS_QUERY: TrendsExtractor(),
    NodeKind.HOG_QL_QUERY: HogQLExtractor(),
    NodeKind.FUNNELS_QUERY: FunnelsExtractor(),
    NodeKind.METRICS_QUERY: MetricsExtractor(),
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


def _query_interval(query: object) -> IntervalType | None:
    # Metrics insights use interval strings outside the enum (``minute_5``, ``$window``).
    try:
        raw_interval = get_from_dict_or_attr(query, "interval")
    except AttributeError:
        return None
    if raw_interval is None:
        return None
    try:
        return IntervalType(raw_interval)
    except ValueError:
        return None


def _ends_in_the_past(query: object, *, now: datetime, team: Team) -> bool:
    # The shared rule caches a closed range forever, and the override would replace that rule.
    try:
        date_range = get_from_dict_or_attr(query, "dateRange")
    except AttributeError:
        return False
    if date_range is None:
        return False
    try:
        date_to = get_from_dict_or_attr(date_range, "date_to")
    except AttributeError:
        return False
    if not isinstance(date_to, str):
        return False
    parsed, delta_mapping, _position = relative_date_parse_with_delta_mapping(date_to, ZoneInfo(team.timezone), now=now)
    return delta_mapping is None and parsed < now


def _resolve_cache_age_seconds(alert: AlertConfiguration, query: object, execution_mode: ExecutionMode) -> int | None:
    # Read for every kind, unlike _resolve_execution_mode, because funnels also hit the cache.
    if execution_mode == ExecutionMode.CALCULATE_BLOCKING_ALWAYS:
        return None
    if get_from_dict_or_attr(query, "kind") == NodeKind.METRICS_QUERY:
        # Metrics already age on a minute threshold, so a bucket limit would loosen it.
        return None
    now = datetime.now(UTC)
    if _ends_in_the_past(query, now=now, team=alert.team):
        return None
    return cache_age_seconds_for_alert(_query_interval(query), now=now, team=alert.team)


@contextmanager
def owner_sql_errors(query: object) -> Iterator[None]:
    """Raise a user-safe failure of a SQL insight's own query as an ``AlertExtractionError``.

    The owner wrote the query, such as a HogQL call with the wrong arguments or a column type
    mismatch, and it fails the same way until they fix it. Other kinds keep the ordinary path,
    because PostHog builds their SQL and the error can be a bug. A transient ClickHouse error also
    keeps the ordinary path, because the query itself can be sound.
    """
    try:
        yield
    except (ExposedHogQLError, ExposedCHQueryError) as err:
        if isinstance(err, CH_TRANSIENT_ERRORS) or get_from_dict_or_attr(query, "kind") != NodeKind.HOG_QL_QUERY:
            raise
        raise AlertExtractionError(str(err)) from err


# Entered around the ClickHouse query alone, so a caller can bound its concurrent queries without
# counting the insight load, the evaluation or a detector's model call.
QuerySlot = Callable[[], AbstractContextManager[object]]


def run_extractor(
    extractor: Extractor,
    alert: AlertConfiguration,
    insight: Insight,
    query: object,
    execution_mode: ExecutionMode,
    query_slot: QuerySlot = nullcontext,
) -> ExtractionResult:
    """Run an extractor, routing a query the runner refuses to the auto-disable path.

    The query layer raises a DRF ValidationError for an insight it can never run as written: a
    validation rule the insight breaks, an action a step points at that no longer exists, a cohort
    property it can no longer resolve. The alert cannot evaluate until someone fixes the insight,
    so it is disabled and its owner emailed, rather than the same failure being captured on every
    scheduled check.

    A breaker replay is not such a verdict. It carries the remembered ClickHouse failure of a query
    that is itself sound (see ``build_failure_exception`` in
    ``posthog/hogql_queries/query_failure_handling.py``), and disabling on it would silence a
    working alert over a load problem, so it keeps the ordinary failure path.

    A SQL insight that HogQL or ClickHouse rejects with a user-safe error gets the same verdict
    (see ``owner_sql_errors``).
    """
    try:
        with query_slot(), owner_sql_errors(query):
            # Resolve inside the slot so a slot wait cannot push the window past a bucket boundary.
            cache_age_seconds = _resolve_cache_age_seconds(alert, query, execution_mode)
            return extractor.extract(alert, insight, query, execution_mode, cache_age_seconds)
    except DRFValidationError as err:
        if getattr(err, "served_from_query_failure_cache", False):
            raise
        raise AlertExtractionError(rule_violation_message(err)) from err


def check_detector_alert(
    alert: AlertConfiguration,
    insight: Insight,
    query: object,
    *,
    evaluation_id: str | None = None,
    query_slot: QuerySlot = nullcontext,
) -> AlertEvaluationResult:
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
    result = run_extractor(
        detector_extractor, alert, insight, query, _resolve_execution_mode(alert, kind, query), query_slot
    )
    return describe_delayed_evaluation(
        evaluate_with_detector(result, detector_config, insight=insight, alert=alert, evaluation_id=evaluation_id),
        result,
    )


@frozen
class _ResolvedQuery:
    insight: Insight
    query: Any
    kind: Any


@contextmanager
def _resolved_query(alert: AlertConfiguration) -> Iterator[_ResolvedQuery]:
    """The alert's insight query, upgraded, unwrapped and checked against its evaluation delay.

    A context manager, because the upgrade holds only while the query runs.
    """
    insight = alert.insight
    if insight.query is None:
        raise ValueError("Alert's insight has no valid query")

    with upgrade_insight(insight):
        query = insight.query
        kind = get_from_dict_or_attr(query, "kind")

        if kind in WRAPPER_NODE_KINDS:
            query = get_from_dict_or_attr(query, "source")
            kind = get_from_dict_or_attr(query, "kind")

        try:
            validate_evaluation_delay(query, alert.config, alert.evaluation_delay_intervals)
        except ValueError as err:
            raise AlertExtractionError(str(err)) from err
        yield _ResolvedQuery(insight=insight, query=query, kind=kind)


def _check_alert_for_insight(
    alert: AlertConfiguration, *, evaluation_id: str | None = None, query_slot: QuerySlot = nullcontext
) -> AlertEvaluationResult:
    """Dispatch an alert to its insight-kind extractor, then run the shared comparator.

    If ``detector_config`` is set, routes through the anomaly-detector registry (one extractor per
    supported insight kind); each detector extractor shares the ``ComparableSeries`` contract, so the
    dispatch shape mirrors the threshold path. Otherwise the extractor normalizes the query result into an
    ``ExtractionResult`` and the comparator evaluates it against the threshold.
    """
    with _resolved_query(alert) as resolved:
        if alert.detector_config:
            return check_detector_alert(
                alert, resolved.insight, resolved.query, evaluation_id=evaluation_id, query_slot=query_slot
            )

        extracted = _extract_for_threshold(alert, resolved.insight, resolved.query, resolved.kind, query_slot)
        if extracted is None:
            return AlertEvaluationResult(value=0, breaches=[])
        return describe_delayed_evaluation(
            evaluate_threshold(extracted.result, extracted.condition, extracted.threshold), extracted.result
        )


@frozen
class _ThresholdExtraction:
    result: ExtractionResult
    condition: AlertCondition
    threshold: InsightThreshold


def _extract_for_threshold(
    alert: AlertConfiguration, insight: Insight, query: object, kind: NodeKind, query_slot: QuerySlot = nullcontext
) -> _ThresholdExtraction | None:
    """Run a threshold alert's query. None when the alert has no bounds, so there is nothing to breach."""
    extractor = EXTRACTORS.get(kind)
    if extractor is None:
        raise NotImplementedError(f"AlertCheckError: Alerts for {kind} are not supported yet")

    # Short-circuit before the (potentially expensive) query: no bounds means nothing to breach.
    threshold = InsightThreshold.model_validate(alert.threshold.configuration) if alert.threshold else None
    if not threshold or not threshold.bounds:
        return None

    condition = AlertCondition.model_validate(alert.condition)
    result = run_extractor(extractor, alert, insight, query, _resolve_execution_mode(alert, kind, query), query_slot)
    return _ThresholdExtraction(result=result, condition=condition, threshold=threshold)


def _one_series(result: ExtractionResult, series: ComparableSeries) -> ExtractionResult:
    """One series as its own result. Not a breakdown any more, so a series that does not breach
    still reports its value, and the label stays in a breach message."""
    return replace(
        result,
        series=[series],
        is_breakdown=False,
        include_series_label=result.is_breakdown or result.include_series_label,
    )


@frozen
class SeriesEvaluation:
    # What per-series state is keyed on. `label` is for display, and two series can share one.
    identity: str
    label: str
    result: AlertEvaluationResult


@frozen
class PerSeriesEvaluation:
    series: tuple[SeriesEvaluation, ...]
    # The breakdown limit folded some values into "Other", so a value not in `series` may still breach.
    truncated: bool = False


def check_alert_per_series(
    alert: AlertConfiguration, *, query_slot: QuerySlot = nullcontext
) -> PerSeriesEvaluation | AlertEvaluationResult:
    """Each series' own verdict for a threshold alert, rather than one verdict for the insight.

    `check_alert_for_insight` stops at the first series that breaches, because one alert holds one
    state. A caller that keeps state per breakdown value needs every series judged on its own.
    Returns the skipped result instead when the evaluation delay leaves no complete interval.
    Detector alerts are not supported, because a detector scores the series together.
    """
    if alert.detector_config:
        raise AlertExtractionError("Per-series evaluation supports threshold alerts only")
    try:
        with _resolved_query(alert) as resolved:
            extracted = _extract_for_threshold(alert, resolved.insight, resolved.query, resolved.kind, query_slot)
    except DelayedEvaluationUnavailable as err:
        return AlertEvaluationResult(value=None, breaches=[], skipped_reason=str(err))
    if extracted is None:
        return PerSeriesEvaluation(series=())
    result = extracted.result
    if result.is_breakdown and result.empty_query_result:
        # The extractor stands in a zero series for a query with no rows. A breakdown with no rows
        # has no values, so that series is not a breakdown value and must not become a group.
        return PerSeriesEvaluation(series=())
    return PerSeriesEvaluation(
        series=tuple(
            SeriesEvaluation(
                identity=series.identity or series.label,
                label=series.label,
                result=describe_delayed_evaluation(
                    evaluate_threshold(_one_series(result, series), extracted.condition, extracted.threshold),
                    result,
                ),
            )
            for series in result.series
        ),
        truncated=result.truncated,
    )


def check_alert_for_insight(
    alert: AlertConfiguration, *, evaluation_id: str | None = None, query_slot: QuerySlot = nullcontext
) -> AlertEvaluationResult:
    try:
        return _check_alert_for_insight(alert, evaluation_id=evaluation_id, query_slot=query_slot)
    except DelayedEvaluationUnavailable as err:
        if is_llm_detector_config(alert.detector_config):
            raise LLMDetectorUnavailableError(str(err)) from err
        return AlertEvaluationResult(
            value=None,
            breaches=[],
            skipped_reason=str(err),
            triggered_metadata={
                "evaluation_delay_intervals": alert.evaluation_delay_intervals,
                "skipped_reason": str(err),
            },
        )
