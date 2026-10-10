"""Pick the insights that are due for anomaly scoring, and score one of them and record the outcome on its state row."""

import json
import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum

from django.db.models import Exists, F, OuterRef, Q, Window
from django.db.models.functions import RowNumber

import structlog

from posthog.dataclasses import frozen
from posthog.schema_enums import IntervalType

from products.alerts.backend.anomaly_scoring.config import EffectiveAnomalyConfig, effective_config
from products.alerts.backend.anomaly_scoring.emit import emit_scores, last_bucket
from products.alerts.backend.anomaly_scoring.scoring import (
    INTERVAL_STEP,
    UnsupportedInsightError,
    detector_version,
    score_insight,
)
from products.alerts.backend.models import AlertConfiguration, InsightAnomalyConfig, InsightAnomalyState
from products.product_analytics.backend.facade.models import Insight

logger = structlog.get_logger(__name__)

# Events keep arriving for a short time after a bucket closes.
INGESTION_LAG = timedelta(minutes=15)
# Lower bound on the time between two runs of one insight, so an insight that is behind does not run every tick.
MIN_RECHECK = timedelta(minutes=5)
FAILURE_BACKOFF_BASE = timedelta(minutes=15)
# Capture drops points older than 24 hours, so a longer backoff loses buckets for good.
FAILURE_BACKOFF_MAX = timedelta(hours=6)
# An edit to the insight or its config makes it due at once, so this only catches fixes on our side.
SKIPPED_RECHECK = timedelta(days=7)
RECENTLY_VIEWED = timedelta(days=30)

# The AI detector makes a charged model call per check. Scoring every bucket of every series would multiply that cost.
REFUSED_DETECTOR_TYPES = frozenset({"llm"})


class ScoreStatus(StrEnum):
    SCORED = "scored"
    SKIPPED = "skipped"
    FAILED = "failed"
    DISABLED = "disabled"
    GONE = "gone"


@frozen
class DueInsight:
    team_id: int
    insight_id: int


@frozen
class ScoreOutcome:
    insight_id: int
    status: ScoreStatus
    written: int = 0
    dropped_stale: int = 0
    last_scored_bucket: datetime | None = None
    reason: str | None = None


def due_insights(now: datetime, *, team_ids: Sequence[int], per_team_limit: int, total_limit: int) -> list[DueInsight]:
    """Saved trends insights that are due, ranked within each team and capped per team and in total.

    An empty ``team_ids`` means every team. Each team's top-ranked insights come first, so one large
    team cannot take the whole tick. Insights left over stay due and run on a later tick.
    """
    tiles = Insight.objects.filter(
        Q(dashboard_tiles__deleted__isnull=True) | Q(dashboard_tiles__deleted=False),
        pk=OuterRef("pk"),
        dashboard_tiles__dashboard__deleted=False,
    )
    views = Insight.objects.filter(pk=OuterRef("pk"), insightviewed__last_viewed_at__gte=now - RECENTLY_VIEWED)
    alerts = AlertConfiguration.objects.filter(insight_id=OuterRef("pk"), enabled=True)

    queryset = (
        Insight.objects.filter(saved=True, deleted=False)
        .filter(Q(query__kind="TrendsQuery") | Q(query__source__kind="TrendsQuery"))
        .exclude(anomaly_config__enabled=False)
        .filter(
            Q(anomaly_state__isnull=True)
            | Q(anomaly_state__next_due_at__isnull=True)
            | Q(anomaly_state__next_due_at__lte=now)
            | Q(last_modified_at__gt=F("anomaly_state__last_run_at"))
            | Q(anomaly_config__updated_at__gt=F("anomaly_state__last_run_at"))
        )
    )
    if team_ids:
        queryset = queryset.filter(team_id__in=team_ids)

    ranked = (
        queryset.annotate(on_dashboard=Exists(tiles), viewed_recently=Exists(views), has_alert=Exists(alerts))
        .annotate(
            team_rank=Window(
                RowNumber(),
                partition_by=[F("team_id")],
                order_by=[
                    F("on_dashboard").desc(),
                    F("viewed_recently").desc(),
                    F("has_alert").desc(),
                    F("created_at").desc(nulls_last=True),
                    F("id").desc(),
                ],
            )
        )
        .filter(team_rank__lte=per_team_limit)
        .order_by("team_rank", "team_id")
        .values_list("team_id", "id")
    )
    return [DueInsight(team_id=team_id, insight_id=insight_id) for team_id, insight_id in ranked[:total_limit]]


def query_hash(insight: Insight, config: EffectiveAnomalyConfig) -> str:
    canonical = json.dumps(
        {
            "query": insight.query,
            "detector": detector_version(config.detector_config),
            "max_breakdowns": config.max_breakdowns,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def next_due_at(last_scored_bucket: datetime | None, interval: IntervalType, now: datetime) -> datetime:
    step = INTERVAL_STEP[interval]
    if last_scored_bucket is None:
        return now + step
    # The bucket after the last scored one starts one step later and closes one step after that.
    return max(last_scored_bucket + 2 * step + INGESTION_LAG, now + MIN_RECHECK)


def failure_backoff(consecutive_failures: int) -> timedelta:
    return min(FAILURE_BACKOFF_BASE * 2 ** max(consecutive_failures - 1, 0), FAILURE_BACKOFF_MAX)


def score_and_record(*, team_id: int, insight_id: int, now: datetime) -> ScoreOutcome:
    """Score one insight, write its new buckets to Metrics and move its state forward.

    A failure never raises. It is recorded on the state row and the insight backs off.
    """
    insight = (
        Insight.objects.select_related("team", "created_by")
        .filter(pk=insight_id, team_id=team_id, deleted=False)
        .first()
    )
    if insight is None:
        return ScoreOutcome(insight_id=insight_id, status=ScoreStatus.GONE)

    override = InsightAnomalyConfig.objects.for_team(team_id).filter(insight=insight).first()
    config = effective_config(override)
    if not config.enabled:
        return ScoreOutcome(insight_id=insight_id, status=ScoreStatus.DISABLED)

    state, _ = InsightAnomalyState.objects.for_team(team_id).get_or_create(team_id=team_id, insight=insight)
    current_hash = query_hash(insight, config)
    if state.query_hash != current_hash:
        # last_scored_bucket stays. Capture cannot take old points, and the same labels on a rewritten
        # bucket would leave two points at one timestamp.
        state.query_hash = current_hash
        state.skip_reason = None
        state.consecutive_failures = 0
    state.last_run_at = now

    try:
        detector_type = config.detector_config.get("type")
        if detector_type in REFUSED_DETECTOR_TYPES:
            raise UnsupportedInsightError(f"The {detector_type} detector does not score insights")
        scores = score_insight(insight, insight.team, config, now=now, after=state.last_scored_bucket)
        result = emit_scores(team=insight.team, insight_id=insight.pk, scores=scores, now=now)
    except UnsupportedInsightError as err:
        state.skip_reason = str(err)[:200]
        state.next_due_at = now + SKIPPED_RECHECK
        state.save()
        return ScoreOutcome(insight_id=insight_id, status=ScoreStatus.SKIPPED, reason=state.skip_reason)
    except Exception as err:
        logger.exception("insight_anomaly_scoring_failed", team_id=team_id, insight_id=insight_id)
        state.consecutive_failures += 1
        state.last_error = repr(err)[:2000]
        state.next_due_at = now + failure_backoff(state.consecutive_failures)
        state.save()
        return ScoreOutcome(insight_id=insight_id, status=ScoreStatus.FAILED, reason=state.last_error)

    newest = last_bucket(scores)
    if newest is not None:
        # Metrics samples are append-only, so a bucket written twice leaves two points at one timestamp.
        state.last_scored_bucket = newest
    state.skip_reason = None
    state.last_error = None
    state.consecutive_failures = 0
    state.next_due_at = next_due_at(state.last_scored_bucket, scores.interval, now)
    state.save()
    return ScoreOutcome(
        insight_id=insight_id,
        status=ScoreStatus.SCORED,
        written=result.written,
        dropped_stale=result.dropped_stale,
        last_scored_bucket=state.last_scored_bucket,
    )
