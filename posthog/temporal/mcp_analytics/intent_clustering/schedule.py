"""Daily schedule for the MCP analytics intent clustering coordinator.

Gated behind the ``mcp-analytics-clustering-schedule`` PostHog feature flag.
This is a kill switch: the schedule isn't registered when the flag is off,
which keeps the daily fan-out from kicking before the dedicated
``mcp-analytics-task-queue`` worker exists in production. Flipping the
flag off after a deploy also removes the schedule on next init, so we can
disable the daily path without rolling back code.
"""

from datetime import timedelta

from django.conf import settings

import structlog
import posthoganalytics
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.mcp_analytics.intent_clustering.constants import (
    COORDINATOR_EXECUTION_TIMEOUT,
    COORDINATOR_SCHEDULE_ID,
    COORDINATOR_WORKFLOW_NAME,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_TOP_N_INTENTS,
)
from posthog.temporal.mcp_analytics.intent_clustering.coordinator import IntentClusteringCoordinatorInputs

logger = structlog.get_logger(__name__)

FEATURE_FLAG_KEY = "mcp-analytics-clustering-schedule"
# Stable distinct_id for the schedule registration check — the decision is
# deployment-scoped, not user-scoped. Matches the LLMA team_discovery
# convention (``internal_llma_team_discovery``).
FEATURE_FLAG_DISTINCT_ID = "internal_mcpa_clustering_schedule"


def _schedule_enabled() -> bool:
    """Return True only when the feature flag is explicitly ON.

    Any FF error (network, missing key, malformed payload) defaults to OFF —
    the schedule registration is the riskier side, so fail-closed is right.
    """
    try:
        enabled = posthoganalytics.feature_enabled(FEATURE_FLAG_KEY, FEATURE_FLAG_DISTINCT_ID)
        return bool(enabled)
    except Exception:
        logger.warning("mcpa.intent_clustering.schedule.feature_flag_check_failed_defaulting_off", exc_info=True)
        return False


async def create_intent_clustering_coordinator_schedule(client: Client) -> None:
    """Register (or update) the daily intent clustering coordinator schedule.

    When the feature flag is OFF, any existing schedule is deleted so flipping
    the flag off cleanly disables the daily path. The schedule is created
    with ``trigger_immediately=False`` to avoid stampeding a worker on first
    deploy.
    """
    if not _schedule_enabled():
        if await a_schedule_exists(client, COORDINATOR_SCHEDULE_ID):
            logger.info(
                "mcpa.intent_clustering.schedule.disabled_removing_existing", schedule_id=COORDINATOR_SCHEDULE_ID
            )
            await a_delete_schedule(client, COORDINATOR_SCHEDULE_ID)
        else:
            logger.info("mcpa.intent_clustering.schedule.disabled_no_action", schedule_id=COORDINATOR_SCHEDULE_ID)
        return

    coordinator_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            COORDINATOR_WORKFLOW_NAME,
            IntentClusteringCoordinatorInputs(
                lookback_days=DEFAULT_LOOKBACK_DAYS,
                top_n=DEFAULT_TOP_N_INTENTS,
            ),
            id=COORDINATOR_SCHEDULE_ID,
            task_queue=settings.MCPA_TASK_QUEUE,
            execution_timeout=COORDINATOR_EXECUTION_TIMEOUT,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(days=1))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, COORDINATOR_SCHEDULE_ID):
        logger.info("mcpa.intent_clustering.schedule.updating", schedule_id=COORDINATOR_SCHEDULE_ID)
        await a_update_schedule(client, COORDINATOR_SCHEDULE_ID, coordinator_schedule)
    else:
        logger.info("mcpa.intent_clustering.schedule.creating", schedule_id=COORDINATOR_SCHEDULE_ID)
        await a_create_schedule(
            client,
            COORDINATOR_SCHEDULE_ID,
            coordinator_schedule,
            trigger_immediately=False,
        )


async def delete_intent_clustering_coordinator_schedule(client: Client) -> None:
    """Explicit-delete helper. Used by tests; not wired into init_schedules."""
    await a_delete_schedule(client, COORDINATOR_SCHEDULE_ID)
