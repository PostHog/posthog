import math
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Literal

from django.conf import settings

import structlog
import posthoganalytics
from prometheus_client import Counter, Histogram
from temporalio.exceptions import CancelledError

from posthog.schema import HogQLAlertEvaluation, HogQLQuery, NodeKind, TrendsQuery

from posthog.caching.insight_result import InsightResult
from posthog.dataclasses import frozen
from posthog.errors import CHQueryErrorQueryWasCancelled
from posthog.event_usage import groups
from posthog.hogql_queries.apply_dashboard_filters import dashboard_filter_from_dict
from posthog.models.team import Team
from posthog.models.user import User

from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.contracts import (
    ClosedSeriesValues,
    ClosedSqlSeriesValues,
    SeriesValuesUnavailable,
    SeriesValuesVerification,
)
from products.product_analytics.backend.facade.queries import (
    TrendsQueryRunner,
    closed_series_values,
    closed_sql_series_values,
)

logger = structlog.get_logger(__name__)

SERIES_VALUES_PRECOMPUTE_FLAG = "alerts-series-values-precompute"
SHADOW_COMPARISON_EVENT = "alert series values shadow compared"
SHADOW_BUILD_BUDGET_SECONDS = 60
SQL_RELATIVE_TOLERANCE = 1e-9

AlertKind = Literal["threshold", "detector"]
ShadowOutcome = Literal["match", "mismatch", "unavailable", "error"]
_CANCELLATION = (CancelledError, CHQueryErrorQueryWasCancelled)

_SHADOW_COMPARISON_COUNTER = Counter(
    "posthog_insight_alerts_series_values_shadow_total",
    "Alert checks by the outcome of comparing their live values with stored closed-day values",
    labelnames=["outcome", "insight_kind"],
)
_SHADOW_COMPARISON_DURATION = Histogram(
    "posthog_insight_alerts_series_values_shadow_duration_seconds",
    "Wall-clock time of the series values shadow step in a trends alert check, including any inline build",
    labelnames=["outcome"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)


@frozen
class ShadowComparison:
    outcome: ShadowOutcome
    reason: str | None = None
    buckets_compared: int = 0
    max_abs_difference: float = 0.0
    freshly_built: bool = False
    verification: SeriesValuesVerification | None = None


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
    except Exception:
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
    if not differences:
        return ShadowComparison(
            outcome="unavailable",
            reason="no_overlapping_buckets",
            freshly_built=closed.freshly_built,
            verification=closed.verification,
        )
    largest = max(differences)
    return ShadowComparison(
        outcome="match" if largest == 0 else "mismatch",
        buckets_compared=len(differences),
        max_abs_difference=largest,
        freshly_built=closed.freshly_built,
        verification=closed.verification,
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
            closed = closed_series_values(
                runner, run_inserts=True, wait_timeout_seconds=SHADOW_BUILD_BUDGET_SECONDS, verify=True
            )
            comparison = compare_closed_values(closed, live)
    except _CANCELLATION:
        raise
    except Exception as err:
        logger.exception("alert_series_values_shadow_failed", team_id=alert.team_id, alert_id=str(alert.id))
        comparison = ShadowComparison(outcome="error", reason=type(err).__name__)
    _record(alert, alert_kind, "trends", comparison, duration_seconds=time.monotonic() - started)


def _bucket_instant(cell: Any) -> datetime:
    if isinstance(cell, str):
        cell = datetime.fromisoformat(cell)
    if isinstance(cell, datetime):
        return cell.astimezone(UTC) if cell.tzinfo else cell.replace(tzinfo=UTC)
    if isinstance(cell, date):
        return datetime(cell.year, cell.month, cell.day, tzinfo=UTC)
    raise TypeError(f"Unsupported bucket value {type(cell).__name__}")


def compare_closed_sql_values(
    closed: ClosedSqlSeriesValues | SeriesValuesUnavailable,
    rows: list,
    column_names: list[str] | None,
    value_column: str,
) -> ShadowComparison:
    if isinstance(closed, SeriesValuesUnavailable):
        return ShadowComparison(outcome="unavailable", reason=closed.reason)
    if not column_names or closed.bucket_column not in column_names or value_column not in column_names:
        return ShadowComparison(outcome="unavailable", reason="result_columns", freshly_built=closed.freshly_built)
    bucket_index = column_names.index(closed.bucket_column)
    value_index = column_names.index(value_column)
    live = {
        _bucket_instant(row[bucket_index]): 0.0 if row[value_index] is None else float(row[value_index]) for row in rows
    }
    first, last = min(live), max(live)
    buckets = {
        bucket
        for bucket in live.keys() | closed.values.keys()
        if first < bucket <= last and bucket < closed.closed_before
    }
    if not buckets:
        return ShadowComparison(
            outcome="unavailable", reason="no_overlapping_buckets", freshly_built=closed.freshly_built
        )
    pairs = [(live.get(bucket, 0.0), closed.values.get(bucket, 0.0)) for bucket in buckets]
    return ShadowComparison(
        outcome="match" if all(math.isclose(a, b, rel_tol=SQL_RELATIVE_TOLERANCE) for a, b in pairs) else "mismatch",
        buckets_compared=len(pairs),
        max_abs_difference=max(abs(a - b) for a, b in pairs),
        freshly_built=closed.freshly_built,
    )


def _sql_comparison(
    alert: AlertConfiguration,
    source: dict | None,
    rows: list,
    column_names: list[str] | None,
    resolve_value_column: Callable[[], str | None],
    evaluation: HogQLAlertEvaluation,
) -> ShadowComparison:
    if evaluation == HogQLAlertEvaluation.ANY_ROW:
        return ShadowComparison(outcome="unavailable", reason="any_row_evaluation")
    if not rows:
        return ShadowComparison(outcome="unavailable", reason="no_live_result")
    value_column = None if source is None else resolve_value_column()
    if source is None or value_column is None:
        return ShadowComparison(outcome="unavailable", reason="value_column")
    closed = closed_sql_series_values(
        alert.team,
        HogQLQuery.model_validate(source),
        value_column=value_column,
        run_inserts=True,
        wait_timeout_seconds=SHADOW_BUILD_BUDGET_SECONDS,
    )
    return compare_closed_sql_values(closed, rows, column_names, value_column)


def compare_sql_series_values_shadow(
    alert: AlertConfiguration,
    source: dict | None,
    rows: list,
    column_names: list[str] | None,
    *,
    resolve_value_column: Callable[[], str | None],
    evaluation: HogQLAlertEvaluation,
    alert_kind: AlertKind,
) -> None:
    started = time.monotonic()
    try:
        if not is_series_values_precompute_enabled(alert.team):
            return
        comparison = _sql_comparison(alert, source, rows, column_names, resolve_value_column, evaluation)
    except _CANCELLATION:
        raise
    except Exception as err:
        logger.exception("alert_series_values_shadow_failed", team_id=alert.team_id, alert_id=str(alert.id))
        comparison = ShadowComparison(outcome="error", reason=type(err).__name__)
    _record(alert, alert_kind, NodeKind.HOG_QL_QUERY.value, comparison, duration_seconds=time.monotonic() - started)


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
) -> None:
    try:
        _SHADOW_COMPARISON_COUNTER.labels(outcome=comparison.outcome, insight_kind=insight_kind).inc()
        if duration_seconds is not None:
            _SHADOW_COMPARISON_DURATION.labels(outcome=comparison.outcome).observe(duration_seconds)
        team = alert.team
        verification = comparison.verification
        posthoganalytics.capture(
            event=SHADOW_COMPARISON_EVENT,
            distinct_id=str(team.uuid),
            properties={
                "outcome": comparison.outcome,
                "reason": comparison.reason,
                "buckets_compared": comparison.buckets_compared,
                "max_abs_difference": comparison.max_abs_difference,
                "alert_id": str(alert.id),
                "calculation_interval": alert.calculation_interval,
                "alert_kind": alert_kind,
                "insight_kind": insight_kind,
                "duration_ms": None if duration_seconds is None else round(duration_seconds * 1000),
                "freshly_built": comparison.freshly_built,
                "verified": verification is not None,
                "stale_days": 0 if verification is None else verification.stale_days,
                "verify_duration_ms": None if verification is None else verification.duration_ms,
            },
            groups=groups(team.organization, team),
        )
    except _CANCELLATION:
        raise
    except Exception:
        logger.exception("alert_series_values_shadow_record_failed", team_id=alert.team_id, alert_id=str(alert.id))
