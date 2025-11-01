import asyncio
from dataclasses import asdict
from datetime import timedelta

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from temporalio import common
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleCalendarSpec,
    ScheduleIntervalSpec,
    ScheduleRange,
    ScheduleSpec,
)

from posthog.hogql_queries.ai.vector_search_query_runner import LATEST_ACTIONS_EMBEDDING_VERSION
from posthog.temporal.ai import SyncVectorsInputs
from posthog.temporal.ai.sync_vectors import EmbeddingVersion
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.enforce_max_replay_retention.types import EnforceMaxReplayRetentionInput
from posthog.temporal.product_analytics.upgrade_queries_workflow import UpgradeQueriesWorkflowInputs
from posthog.temporal.quota_limiting.run_quota_limiting import RunQuotaLimitingInputs
from posthog.temporal.salesforce_enrichment.workflow import SalesforceEnrichmentInputs
from posthog.temporal.subscriptions.subscription_scheduling_workflow import ScheduleAllSubscriptionsWorkflowInputs

from ee.billing.salesforce_enrichment.constants import DEFAULT_CHUNK_SIZE

logger = structlog.get_logger(__name__)


async def create_sync_vectors_schedule(client: Client):
    sync_vectors_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "ai-sync-vectors",
            asdict(SyncVectorsInputs(embedding_versions=EmbeddingVersion(actions=LATEST_ACTIONS_EMBEDDING_VERSION))),
            id="ai-sync-vectors-schedule",
            task_queue=settings.MAX_AI_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=30))]),
    )
    if await a_schedule_exists(client, "ai-sync-vectors-schedule"):
        await a_update_schedule(client, "ai-sync-vectors-schedule", sync_vectors_schedule)
    else:
        await a_create_schedule(client, "ai-sync-vectors-schedule", sync_vectors_schedule, trigger_immediately=True)


async def create_run_quota_limiting_schedule(client: Client):
    """Create or update the schedule for the RunQuotaLimitingWorkflow.

    This schedule runs every 15 minutes.
    """
    run_quota_limiting_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "run-quota-limiting",
            asdict(RunQuotaLimitingInputs()),
            id="run-quota-limiting-schedule",
            task_queue=settings.BILLING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=["10,25,40,55 * * * *"]),  # Run at minutes 10, 25, 40, and 55 of every hour
    )

    if await a_schedule_exists(client, "run-quota-limiting-schedule"):
        await a_update_schedule(client, "run-quota-limiting-schedule", run_quota_limiting_schedule)
    else:
        await a_create_schedule(
            client, "run-quota-limiting-schedule", run_quota_limiting_schedule, trigger_immediately=False
        )


async def create_schedule_all_subscriptions_schedule(client: Client):
    """Create or update the schedule for the ScheduleAllSubscriptionsWorkflow.

    This schedule runs every hour at the 55th minute to match the original Celery schedule.
    """
    schedule_all_subscriptions_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "schedule-all-subscriptions",
            asdict(ScheduleAllSubscriptionsWorkflowInputs()),
            id="schedule-all-subscriptions-schedule",
            task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=["55 * * * *"]),  # Run at minute 55 of every hour
    )

    if await a_schedule_exists(client, "schedule-all-subscriptions-schedule"):
        await a_update_schedule(client, "schedule-all-subscriptions-schedule", schedule_all_subscriptions_schedule)
    else:
        await a_create_schedule(
            client,
            "schedule-all-subscriptions-schedule",
            schedule_all_subscriptions_schedule,
            trigger_immediately=False,
        )


async def create_upgrade_queries_schedule(client: Client):
    """Create or update the schedule for the UpgradeQueriesWorkflow.

    This schedule runs every 6 hours.
    """
    upgrade_queries_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "upgrade-queries",
            asdict(UpgradeQueriesWorkflowInputs()),
            id="upgrade-queries-schedule",
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=6))]),
    )

    if await a_schedule_exists(client, "upgrade-queries-schedule"):
        await a_update_schedule(client, "upgrade-queries-schedule", upgrade_queries_schedule)
    else:
        await a_create_schedule(client, "upgrade-queries-schedule", upgrade_queries_schedule, trigger_immediately=False)


async def create_salesforce_enrichment_schedule(client: Client):
    """Create or update the schedule for the Salesforce enrichment workflow.

    This schedule runs every Sunday at 2 AM UTC with default chunk size.
    """
    salesforce_enrichment_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "salesforce-enrichment-async",
            SalesforceEnrichmentInputs(chunk_size=DEFAULT_CHUNK_SIZE),
            id="salesforce-enrichment-schedule",
            task_queue=settings.BILLING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Sunday at 2 AM UTC",
                    hour=[ScheduleRange(start=2, end=2)],
                    day_of_week=[ScheduleRange(start=0, end=0)],
                )
            ]
        ),
    )

    if await a_schedule_exists(client, "salesforce-enrichment-schedule"):
        await a_update_schedule(client, "salesforce-enrichment-schedule", salesforce_enrichment_schedule)
    else:
        await a_create_schedule(
            client, "salesforce-enrichment-schedule", salesforce_enrichment_schedule, trigger_immediately=False
        )


async def create_enforce_max_replay_retention_schedule(client: Client):
    """Create or update the schedule for the enforce max replay retention workflow.

    This schedule runs daily at 1 AM UTC.
    """
    enforce_max_replay_retention_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "enforce-max-replay-retention",
            EnforceMaxReplayRetentionInput(dry_run=False),
            id="enforce-max-replay-retention-schedule",
            task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
            retry_policy=common.RetryPolicy(
                maximum_attempts=1,
            ),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 1 AM UTC",
                    hour=[ScheduleRange(start=1, end=1)],
                )
            ]
        ),
    )

    if await a_schedule_exists(client, "enforce-max-replay-retention-schedule"):
        await a_update_schedule(client, "enforce-max-replay-retention-schedule", enforce_max_replay_retention_schedule)
    else:
        await a_create_schedule(
            client,
            "enforce-max-replay-retention-schedule",
            enforce_max_replay_retention_schedule,
            trigger_immediately=False,
        )


schedules = [
    create_sync_vectors_schedule,
    create_run_quota_limiting_schedule,
    create_upgrade_queries_schedule,
    create_enforce_max_replay_retention_schedule,
]

if settings.EE_AVAILABLE:
    schedules.append(create_schedule_all_subscriptions_schedule)
    if settings.CLOUD_DEPLOYMENT == "US":
        schedules.append(create_salesforce_enrichment_schedule)


async def a_init_general_queue_schedules():
    temporal = await async_connect()
    try:
        async with asyncio.TaskGroup() as tg:
            for schedule in schedules:
                tg.create_task(schedule(temporal))
    except* Exception as eg:
        for exc in eg.exceptions:
            logger.exception("Failed to initialize temporal schedules", error=exc)
            if not isinstance(exc, ScheduleAlreadyRunningError):
                raise exc


@async_to_sync
async def init_schedules():
    await a_init_general_queue_schedules()
