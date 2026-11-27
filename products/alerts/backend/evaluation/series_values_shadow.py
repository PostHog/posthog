import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Literal

import structlog
import posthoganalytics
from temporalio.exceptions import CancelledError

from posthog.schema import ChartDisplayType, EventsNode, IntervalType, TrendsQuery

from posthog.hogql.constants import HogQLGlobalSettings

from posthog.caching.insight_result import InsightResult
from posthog.dataclasses import frozen
from posthog.errors import CHQueryErrorQueryWasCancelled
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.apply_dashboard_filters import dashboard_filter_from_dict
from posthog.models.team import Team
from posthog.models.user import User
from posthog.tasks.alerts.trends import _has_breakdown

from products.alerts.backend.evaluation.attempt_budget import attempt_outlasts
from products.alerts.backend.evaluation.query_slot import QuerySlotFull
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.contracts import PrecomputedSeriesValues, SeriesValuesUnavailable
from products.product_analytics.backend.facade.queries import (
    TrendsQueryRunner,
    precomputed_series_values,
    rewriting_series_values,
)

logger = structlog.get_logger(__name__)

SERIES_VALUES_PRECOMPUTE_FLAG = "alerts-series-values-precompute"
SERIES_VALUES_SERVE_FLAG = "alerts-series-values-serve"
SHADOW_COMPARISON_EVENT = "alert series values shadow compared"
SHADOW_BUILD_BUDGET_SECONDS = 60
# The shadow run reads only stored rows, after the build. The cap keeps a slow read inside the margin below.
SHADOW_READ_MAX_SECONDS = 10
# The build can pass its budget by the time it takes to print one INSERT, and the read follows it, so the
# attempt needs more than the budget left.
SHADOW_ATTEMPT_MARGIN_SECONDS = 30

AlertKind = Literal["threshold", "detector"]
ShadowOutcome = Literal["match", "mismatch", "partial", "unavailable", "error"]
_CANCELLATION = (CancelledError, CHQueryErrorQueryWasCancelled)


@frozen
class ShadowComparison:
    outcome: ShadowOutcome
    reason: str | None = None
    buckets_compared: int = 0
    buckets_missing: int = 0
    max_abs_difference: float = 0.0
    freshly_built: bool = False
    features: tuple[str, ...] = ()


def _flag_enabled(team: Team, key: str) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                key,
                str(team.uuid),
                groups={
                    "organization": str(team.organization_id),
                    "project": str(team.id),
                },
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id), "uuid": str(team.uuid)},
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except _CANCELLATION:
        raise
    except Exception as err:
        capture_exception(err, {"feature": "alerts", "phase": "series_values_flag_check", "team_id": team.pk})
        return False


def _can_serve(query: TrendsQuery) -> bool:
    # The shadow validates one result series. Comparisons, formulas and specialized displays can return more.
    trends = query.trendsFilter
    return (
        len(query.series) == 1
        and isinstance(query.series[0], EventsNode)
        and query.series[0].math in (None, "total")
        and query.interval in (None, IntervalType.DAY, IntervalType.HOUR)
        and not query.modifiers
        and not _has_breakdown(query)
        and not (query.compareFilter and query.compareFilter.compare)
        and not (trends and (trends.formulaNodes or trends.formulas or trends.formula))
        and (
            not trends
            or trends.display
            in (
                None,
                ChartDisplayType.AUTO,
                ChartDisplayType.ACTIONS_LINE_GRAPH,
                ChartDisplayType.ACTIONS_AREA_GRAPH,
                ChartDisplayType.ACTIONS_BAR,
                ChartDisplayType.ACTIONS_STACKED_BAR,
                ChartDisplayType.ACTIONS_UNSTACKED_BAR,
            )
        )
    )


def calculate_alert_trends(
    alert: AlertConfiguration | None,
    query: TrendsQuery,
    filters_override: dict | None,
    *,
    alert_kind: AlertKind,
    calculate: Callable[[], InsightResult],
) -> InsightResult:
    if alert is None:
        return calculate()

    if _can_serve(query) and _flag_enabled(alert.team, SERIES_VALUES_SERVE_FLAG):
        with rewriting_series_values("serve", build_on_miss=False) as rewrite:
            result = calculate()
        # A serving-cache hit may also contain stored values. Neither is an independent shadow baseline.
        if rewrite.built or result.is_cached:
            return result
    else:
        result = calculate()

    compare_series_values_shadow(alert, query, filters_override, result, alert_kind=alert_kind)
    return result


def effective_trends_runner(
    team: Team, query: TrendsQuery, filters_override: dict | None, user: User | None
) -> TrendsQueryRunner:
    runner = TrendsQueryRunner(
        query=query.model_copy(deep=True),
        team=team,
        user=user,
        hogql_settings=HogQLGlobalSettings(max_execution_time=SHADOW_READ_MAX_SECONDS),
    )
    if filters_override:
        runner.apply_dashboard_filters(dashboard_filter_from_dict(filters_override))
    return runner


def compare_precomputed_values(
    precomputed: PrecomputedSeriesValues | SeriesValuesUnavailable, live: list[Any]
) -> ShadowComparison:
    if isinstance(precomputed, SeriesValuesUnavailable):
        return ShadowComparison(outcome="unavailable", reason=precomputed.reason.value)
    features = tuple(sorted(feature.value for feature in precomputed.features))
    series = live[0]
    live_by_bucket = {datetime.fromisoformat(day): value for day, value in zip(series["days"], series["data"])}
    differences = [
        abs(float(live_by_bucket[bucket]) - stored)
        for bucket, stored in precomputed.values.items()
        if bucket in live_by_bucket
    ]
    missing = len(precomputed.values) - len(differences)
    if not differences:
        return ShadowComparison(
            outcome="unavailable",
            reason="no_overlapping_buckets",
            buckets_missing=missing,
            freshly_built=precomputed.freshly_built,
            features=features,
        )
    largest = max(differences)
    outcome: ShadowOutcome
    if largest != 0:
        outcome = "mismatch"
    elif missing:
        outcome = "partial"
    else:
        outcome = "match"
    return ShadowComparison(
        outcome=outcome,
        buckets_compared=len(differences),
        buckets_missing=missing,
        max_abs_difference=largest,
        freshly_built=precomputed.freshly_built,
        features=features,
    )


@frozen
class ShadowComparisonRequest:
    """A shadow comparison that a check asked for, to run after the check, in a query slot of its own."""

    alert: AlertConfiguration
    query: TrendsQuery
    filters_override: dict | None
    calculation_result: InsightResult
    alert_kind: AlertKind

    def run(self, query_slot: Callable[[], AbstractContextManager[object]]) -> None:
        started = time.monotonic()
        try:
            live = self.calculation_result.result
            if not live:
                comparison = ShadowComparison(outcome="unavailable", reason="no_live_result")
            elif len(live) > 1:
                # The comparison takes the first series of both results. An alert on a result with several
                # may watch another one, and a match on the first would say nothing about it.
                comparison = ShadowComparison(outcome="unavailable", reason="multiple_series")
            elif not attempt_outlasts(SHADOW_BUILD_BUDGET_SECONDS + SHADOW_ATTEMPT_MARGIN_SECONDS):
                # A shared build can outlive its caller. Leave enough time to record the live result.
                comparison = ShadowComparison(outcome="unavailable", reason="attempt_out_of_time")
            else:
                comparison = self._compare_in(query_slot, live)
        except CancelledError:
            raise
        except CHQueryErrorQueryWasCancelled:
            # The failed-check cleanup cancels the queries of an attempt that stopped. A query cancelled while the
            # attempt runs on was cancelled by someone else, such as an operator, and the check's live result stands.
            if not attempt_outlasts(0):
                raise
            comparison = ShadowComparison(outcome="unavailable", reason="query_cancelled")
        except Exception as err:
            capture_exception(
                err,
                {
                    "feature": "alerts",
                    "phase": "series_values_shadow",
                    "team_id": self.alert.team_id,
                    "alert_id": str(self.alert.id),
                },
            )
            comparison = ShadowComparison(outcome="error", reason=type(err).__name__)
        _record(
            self.alert,
            self.alert_kind,
            "trends",
            comparison,
            duration_seconds=time.monotonic() - started,
            live_cached=self.calculation_result.is_cached,
        )

    def _compare_in(
        self, query_slot: Callable[[], AbstractContextManager[object]], live: list[Any]
    ) -> ShadowComparison:
        try:
            # The build and the read are ClickHouse queries, so they count against the caller's query cap.
            with query_slot():
                runner = effective_trends_runner(
                    self.alert.team, self.query, self.filters_override, self.alert.created_by
                )
                precomputed = precomputed_series_values(runner, wait_timeout_seconds=SHADOW_BUILD_BUDGET_SECONDS)
        except QuerySlotFull:
            return ShadowComparison(outcome="unavailable", reason="no_query_slot")
        return compare_precomputed_values(precomputed, live)


# The shadow comparisons that the check in progress asked for. A build can take a minute, so a caller
# that wants them collects them during the check and runs each one afterwards, in a query slot of its
# own. Without a collector nothing is shadowed.
_requested: ContextVar[list[ShadowComparisonRequest] | None] = ContextVar("series_values_shadow_requests", default=None)


@contextmanager
def collecting_shadow_comparisons() -> Iterator[list[ShadowComparisonRequest]]:
    requested: list[ShadowComparisonRequest] = []
    token = _requested.set(requested)
    try:
        yield requested
    finally:
        _requested.reset(token)


def compare_series_values_shadow(
    alert: AlertConfiguration,
    query: TrendsQuery,
    filters_override: dict | None,
    calculation_result: InsightResult,
    *,
    alert_kind: AlertKind,
) -> None:
    requested = _requested.get()
    if requested is not None and _flag_enabled(alert.team, SERIES_VALUES_PRECOMPUTE_FLAG):
        requested.append(
            ShadowComparisonRequest(
                alert=alert,
                query=query,
                filters_override=filters_override,
                calculation_result=calculation_result,
                alert_kind=alert_kind,
            )
        )


def record_unsupported_insight_kind(alert: AlertConfiguration, insight_kind: str) -> None:
    try:
        if _requested.get() is None or not _flag_enabled(alert.team, SERIES_VALUES_PRECOMPUTE_FLAG):
            return
        _record(
            alert,
            "detector" if alert.detector_config else "threshold",
            insight_kind,
            ShadowComparison(outcome="unavailable", reason="unsupported_insight_kind"),
            duration_seconds=None,
        )
    except _CANCELLATION:
        raise
    except Exception:
        logger.exception("alert_series_values_shadow_record_failed", team_id=alert.team_id, alert_id=str(alert.id))


def _record(
    alert: AlertConfiguration,
    alert_kind: AlertKind,
    insight_kind: str,
    comparison: ShadowComparison,
    *,
    duration_seconds: float | None,
    live_cached: bool | None = None,
) -> None:
    try:
        team = alert.team
        posthoganalytics.capture(
            event=SHADOW_COMPARISON_EVENT,
            distinct_id=str(team.uuid),
            properties={
                "outcome": comparison.outcome,
                "reason": comparison.reason,
                "buckets_compared": comparison.buckets_compared,
                "buckets_missing": comparison.buckets_missing,
                "max_abs_difference": comparison.max_abs_difference,
                "features": list(comparison.features),
                "alert_id": str(alert.id),
                "calculation_interval": alert.calculation_interval,
                "alert_kind": alert_kind,
                "insight_kind": insight_kind,
                "duration_ms": None if duration_seconds is None else round(duration_seconds * 1000),
                "freshly_built": comparison.freshly_built,
                "live_cached": live_cached,
            },
            groups=groups(team.organization, team),
        )
    except _CANCELLATION:
        raise
    except Exception:
        logger.exception("alert_series_values_shadow_record_failed", team_id=alert.team_id, alert_id=str(alert.id))
