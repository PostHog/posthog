import time
from datetime import datetime
from typing import Any, Literal

from django.conf import settings

import structlog
import posthoganalytics
from temporalio.exceptions import CancelledError

from posthog.schema import TrendsQuery

from posthog.caching.insight_result import InsightResult
from posthog.dataclasses import frozen
from posthog.errors import CHQueryErrorQueryWasCancelled
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.apply_dashboard_filters import dashboard_filter_from_dict
from posthog.models.team import Team
from posthog.models.user import User

from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.contracts import ClosedSeriesValues, SeriesValuesUnavailable
from products.product_analytics.backend.facade.queries import TrendsQueryRunner, closed_series_values

logger = structlog.get_logger(__name__)

SERIES_VALUES_PRECOMPUTE_FLAG = "alerts-series-values-precompute"
SHADOW_COMPARISON_EVENT = "alert series values shadow compared"
SHADOW_BUILD_BUDGET_SECONDS = 60

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


def is_series_values_precompute_enabled(team: Team) -> bool:
    try:
        if team.id in settings.ALERTS_SERIES_VALUES_PRECOMPUTE_TEAM_IDS:
            return True
        return bool(
            posthoganalytics.feature_enabled(
                SERIES_VALUES_PRECOMPUTE_FLAG,
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
        logger.exception("alert_series_values_flag_check_failed", team_id=team.pk)
        return False


def effective_trends_runner(
    team: Team, query: TrendsQuery, filters_override: dict | None, user: User | None
) -> TrendsQueryRunner:
    runner = TrendsQueryRunner(query=query.model_copy(deep=True), team=team, user=user)
    if filters_override:
        runner.apply_dashboard_filters(dashboard_filter_from_dict(filters_override))
    return runner


def compare_closed_values(closed: ClosedSeriesValues | SeriesValuesUnavailable, live: list[Any]) -> ShadowComparison:
    if isinstance(closed, SeriesValuesUnavailable):
        return ShadowComparison(outcome="unavailable", reason=closed.reason)
    series = live[0]
    live_by_bucket = {datetime.fromisoformat(day): value for day, value in zip(series["days"], series["data"])}
    differences = [
        abs(float(live_by_bucket[bucket]) - stored)
        for bucket, stored in closed.values.items()
        if bucket in live_by_bucket
    ]
    missing = len(closed.values) - len(differences)
    if not differences:
        return ShadowComparison(
            outcome="unavailable",
            reason="no_overlapping_buckets",
            buckets_missing=missing,
            freshly_built=closed.freshly_built,
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
        freshly_built=closed.freshly_built,
    )


def compare_series_values_shadow(
    alert: AlertConfiguration,
    query: TrendsQuery,
    filters_override: dict | None,
    calculation_result: InsightResult,
    *,
    alert_kind: AlertKind,
) -> None:
    started = time.monotonic()
    try:
        if not is_series_values_precompute_enabled(alert.team):
            return
        live = calculation_result.result
        if not live:
            comparison = ShadowComparison(outcome="unavailable", reason="no_live_result")
        else:
            runner = effective_trends_runner(alert.team, query, filters_override, alert.created_by)
            closed = closed_series_values(runner, run_inserts=True, wait_timeout_seconds=SHADOW_BUILD_BUDGET_SECONDS)
            comparison = compare_closed_values(closed, live)
    except _CANCELLATION:
        raise
    except Exception as err:
        capture_exception(
            err,
            {"feature": "alerts", "phase": "series_values_shadow", "team_id": alert.team_id, "alert_id": str(alert.id)},
        )
        logger.exception("alert_series_values_shadow_failed", team_id=alert.team_id, alert_id=str(alert.id))
        comparison = ShadowComparison(outcome="error", reason=type(err).__name__)
    _record(
        alert,
        alert_kind,
        "trends",
        comparison,
        duration_seconds=time.monotonic() - started,
        live_cached=calculation_result.is_cached,
    )


def record_unsupported_insight_kind(alert: AlertConfiguration, insight_kind: str) -> None:
    try:
        if not is_series_values_precompute_enabled(alert.team):
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
