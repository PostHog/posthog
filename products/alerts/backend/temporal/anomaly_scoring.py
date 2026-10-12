"""Scheduled anomaly scoring for saved trends insights, on the self-driving worker.

Each tick finds the due insights, then scores each one in its own activity. Only ids cross the
workflow boundary: the query results and scores stay inside the score activity.
"""

import asyncio
import datetime as dt
from dataclasses import asdict

from django.conf import settings
from django.utils import timezone

import structlog
from temporalio import activity, workflow
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
from posthog.scheduling.jitter import deterministic_offset
from posthog.sync import database_sync_to_async
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.alerts.backend.anomaly_scoring.job import DueInsight, ScoreStatus, due_insights, score_and_record

logger = structlog.get_logger(__name__)

WORKFLOW_NAME = "insight-anomaly-scoring"
SCHEDULE_ID = "insight-anomaly-scoring-schedule"

# Each score activity runs one trends query, so this bounds the ClickHouse load of one tick.
SCORE_CONCURRENCY = 5
_SCORE_TIMEOUT = dt.timedelta(minutes=5)


@frozen
class InsightAnomalyScoringInput:
    # A manual run for one team. It ignores the enabled setting and the team allowlist.
    team_id: int | None = None


@frozen
class FindDueInsightsResult:
    insights: list[DueInsight]
    skipped_reason: str | None = None


@frozen
class ScoreInsightInput:
    team_id: int
    insight_id: int


@frozen
class InsightAnomalyScoringResult:
    due: int = 0
    scored: int = 0
    skipped: int = 0
    failed: int = 0
    skipped_reason: str | None = None


def _find_due(inputs: InsightAnomalyScoringInput) -> FindDueInsightsResult:
    if inputs.team_id is not None:
        team_ids = [inputs.team_id]
    elif not settings.INSIGHT_ANOMALY_SCORING_ENABLED:
        return FindDueInsightsResult(insights=[], skipped_reason="disabled")
    else:
        team_ids = settings.INSIGHT_ANOMALY_SCORING_TEAM_IDS
    insights = due_insights(
        timezone.now(),
        team_ids=team_ids,
        per_team_limit=settings.INSIGHT_ANOMALY_SCORING_MAX_PER_TEAM,
        total_limit=settings.INSIGHT_ANOMALY_SCORING_MAX_PER_TICK,
    )
    return FindDueInsightsResult(insights=insights)


@activity.defn
@scoped_temporal()
@close_db_connections
async def find_due_insights_activity(inputs: InsightAnomalyScoringInput) -> FindDueInsightsResult:
    return await database_sync_to_async(_find_due, thread_sensitive=False)(inputs)


def _score(inputs: ScoreInsightInput) -> ScoreStatus:
    outcome = score_and_record(team_id=inputs.team_id, insight_id=inputs.insight_id, now=timezone.now())
    logger.info(
        "insight_anomaly_scored",
        team_id=inputs.team_id,
        insight_id=inputs.insight_id,
        status=outcome.status.value,
        written=outcome.written,
        dropped_stale=outcome.dropped_stale,
        reason=outcome.reason,
    )
    return outcome.status


@activity.defn
@scoped_temporal()
@close_db_connections
async def score_insight_activity(inputs: ScoreInsightInput) -> ScoreStatus:
    return await database_sync_to_async(_score, thread_sensitive=False)(inputs)


@workflow.defn(name=WORKFLOW_NAME)
class InsightAnomalyScoringWorkflow:
    @workflow.run
    async def run(self, inputs: InsightAnomalyScoringInput) -> InsightAnomalyScoringResult:
        found = await workflow.execute_activity(
            find_due_insights_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        if found.skipped_reason is not None:
            return InsightAnomalyScoringResult(skipped_reason=found.skipped_reason)

        statuses: list[ScoreStatus | BaseException] = []
        for start in range(0, len(found.insights), SCORE_CONCURRENCY):
            batch = found.insights[start : start + SCORE_CONCURRENCY]
            statuses += await asyncio.gather(
                *(
                    workflow.execute_activity(
                        score_insight_activity,
                        ScoreInsightInput(team_id=due.team_id, insight_id=due.insight_id),
                        start_to_close_timeout=_SCORE_TIMEOUT,
                        # No retry: the activity records its own failures and backs the insight off.
                        # A timed-out attempt can still be writing, so a retry could write its points twice.
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                    for due in batch
                ),
                return_exceptions=True,
            )

        return InsightAnomalyScoringResult(
            due=len(found.insights),
            scored=sum(1 for status in statuses if status == ScoreStatus.SCORED),
            skipped=sum(1 for status in statuses if status == ScoreStatus.SKIPPED),
            failed=sum(1 for status in statuses if status == ScoreStatus.FAILED or isinstance(status, BaseException)),
        )


async def create_insight_anomaly_scoring_schedule(client: Client) -> None:
    """Create or update the scoring schedule on the self-driving task queue.

    The schedule exists in every environment. `INSIGHT_ANOMALY_SCORING_ENABLED` gates the work. SKIP
    on overlap: a slow tick leaves the rest due for the next one.
    """
    interval = dt.timedelta(minutes=settings.INSIGHT_ANOMALY_SCORING_INTERVAL_MINUTES)
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            asdict(InsightAnomalyScoringInput()),
            id=SCHEDULE_ID,
            task_queue=settings.SELF_DRIVING_TASK_QUEUE,
            execution_timeout=interval,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=interval, offset=deterministic_offset(SCHEDULE_ID, interval))]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        # Keep the live state, so a deploy does not resume a schedule that an operator paused.
        description = await client.get_schedule_handle(SCHEDULE_ID).describe()
        schedule.state = description.schedule.state
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)


INSIGHT_ANOMALY_SCORING_WORKFLOWS = [InsightAnomalyScoringWorkflow]
INSIGHT_ANOMALY_SCORING_ACTIVITIES = [find_due_insights_activity, score_insight_activity]
