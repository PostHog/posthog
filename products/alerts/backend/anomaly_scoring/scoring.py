import json
import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import numpy as np

from posthog.schema import BreakdownFilter, DateRange, IntervalType, TrendsQuery

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.event_usage import EventSource
from posthog.models import Team
from posthog.schema_migrations.upgrade_manager import upgrade_insight
from posthog.tasks.alerts.detectors.registry import get_detector
from posthog.tasks.alerts.trends import _has_breakdown, _is_non_time_series_trend
from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS

from products.alerts.backend.anomaly_scoring.config import EffectiveAnomalyConfig
from products.product_analytics.backend.facade.models import Insight

INTERVAL_STEP: dict[IntervalType, timedelta] = {
    IntervalType.HOUR: timedelta(hours=1),
    IntervalType.DAY: timedelta(days=1),
    IntervalType.WEEK: timedelta(weeks=1),
}


class UnsupportedInsightError(Exception):
    """The insight can never be scored as written. The caller records it as a skip reason."""


@frozen
class ScoredPoint:
    bucket: datetime
    value: float
    # None while the detector is still filling its training window.
    score: float | None
    flag: bool


@frozen
class ScoredSeries:
    series_index: int
    label: str
    breakdown_value: str | None
    points: list[ScoredPoint]


@frozen
class InsightScores:
    interval: IntervalType
    detector_type: str
    detector_version: str
    series: list[ScoredSeries]


def detector_version(detector_config: dict[str, Any]) -> str:
    """Identifies the scoring behavior, so scores from different configs are never mixed in one series."""
    canonical = json.dumps(detector_config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def trends_query_for(insight: Insight) -> TrendsQuery:
    if insight.query is None:
        raise UnsupportedInsightError("Insight has no query")
    with upgrade_insight(insight):
        query = insight.query
    if query.get("kind") in WRAPPER_NODE_KINDS:
        query = query.get("source") or {}
    if query.get("kind") != "TrendsQuery":
        raise UnsupportedInsightError(f"Only trends insights are scored, not {query.get('kind')}")
    return TrendsQuery.model_validate(query)


def build_scoring_query(query: TrendsQuery, config: EffectiveAnomalyConfig) -> TrendsQuery:
    """Rewrite the insight query to fetch the scorer's lookback instead of the chart's date range.

    Series, filters and formulas stay as they are, so the scores describe the series the chart shows.
    """
    if _is_non_time_series_trend(query):
        raise UnsupportedInsightError("Insight shows a single value, not a time series")
    interval = query.interval or IntervalType.DAY
    lookback = config.lookback_for(interval)
    if lookback is None:
        raise UnsupportedInsightError(f"Interval {interval.value} is not scored")

    days_of_week = query.dateRange.daysOfWeek if query.dateRange else None
    update: dict[str, Any] = {
        "dateRange": DateRange(date_from=f"-{lookback.days}d", daysOfWeek=days_of_week),
        "compareFilter": None,
    }
    if _has_breakdown(query):
        breakdown_filter = query.breakdownFilter or BreakdownFilter()
        # "Other" mixes whichever values fall outside the top N on each run, so it is not one series.
        update["breakdownFilter"] = breakdown_filter.model_copy(
            update={"breakdown_limit": config.max_breakdowns, "breakdown_hide_other_aggregation": True}
        )
    return query.model_copy(update=update)


def score_series(
    values: Sequence[float],
    buckets: Sequence[datetime],
    *,
    detector_config: dict[str, Any],
    interval: IntervalType,
    now: datetime,
    after: datetime | None = None,
) -> list[ScoredPoint]:
    """Score one series and return its completed buckets later than ``after``.

    The detector sees the whole series, including the ongoing bucket, but only completed buckets are
    returned: the metrics store is append-only, so a partial bucket written now would leave a second
    point at the same timestamp once the bucket completes.
    """
    if len(values) != len(buckets):
        raise ValueError("Each value needs a bucket")
    step = INTERVAL_STEP[interval]
    completed = [i for i, bucket in enumerate(buckets) if bucket + step <= now]
    if not completed:
        return []
    # Score only completed buckets, so the partial one never shapes a neighbor's training window.
    last_completed = completed[-1]
    data = np.array(values[: last_completed + 1], dtype=float)
    result = get_detector(detector_config).detect_batch(data)
    triggered = set(result.triggered_indices)

    points: list[ScoredPoint] = []
    for i in completed:
        if after is not None and buckets[i] <= after:
            continue
        score = result.all_scores[i] if i < len(result.all_scores) else None
        points.append(
            ScoredPoint(bucket=buckets[i].astimezone(UTC), value=float(values[i]), score=score, flag=i in triggered)
        )
    return points


def score_insight(
    insight: Insight,
    team: Team,
    config: EffectiveAnomalyConfig,
    *,
    now: datetime,
    after: datetime | None = None,
) -> InsightScores:
    query = trends_query_for(insight)
    scoring_query = build_scoring_query(query, config)
    interval = scoring_query.interval or IntervalType.DAY

    tag_queries(product=Product.PRODUCT_ANALYTICS, feature=Feature.ALERTING)
    calculation = calculate_for_query_based_insight(
        insight,
        team=team,
        execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        # No request user. Run as the insight's creator so warehouse access control resolves for them.
        user=insight.created_by,
        query_override=scoring_query.model_dump(exclude_none=True),
        analytics_props={"source": EventSource.ALERT},
    )
    if calculation.result is None:
        raise RuntimeError(f"No results for insight {insight.pk}")

    timezone = team.timezone_info
    series: list[ScoredSeries] = []
    for position, result in enumerate(cast(list[dict[str, Any]], calculation.result)):
        buckets = [_parse_bucket(day, timezone) for day in result.get("days") or []]
        points = score_series(
            result.get("data") or [],
            buckets,
            detector_config=config.detector_config,
            interval=interval,
            now=now,
            after=after,
        )
        action = result.get("action") or {}
        breakdown_value = result.get("breakdown_value")
        series.append(
            ScoredSeries(
                series_index=action.get("order", position),
                label=str(result.get("label") or ""),
                breakdown_value=_breakdown_label(breakdown_value),
                points=points,
            )
        )
    return InsightScores(
        interval=interval,
        detector_type=str(config.detector_config.get("type")),
        detector_version=detector_version(config.detector_config),
        series=series,
    )


def _parse_bucket(day: str, timezone: ZoneInfo) -> datetime:
    # Trends returns bucket starts as naive strings in the project's timezone.
    return datetime.fromisoformat(day).replace(tzinfo=timezone)


def _breakdown_label(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return "::".join(str(part) for part in value)
    return str(value)
