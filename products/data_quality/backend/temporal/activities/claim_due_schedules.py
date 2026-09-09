from temporalio import activity

from posthog.sync import database_sync_to_async_pool

from ...logic.contracts import ClaimedScheduleBatch
from ...logic.schedules import acknowledge_schedule, claim_due_schedule_batch
from ..contracts import AcknowledgeScheduleInputs, ClaimDueSchedulesInputs


@activity.defn
async def claim_due_schedules_activity(inputs: ClaimDueSchedulesInputs) -> ClaimedScheduleBatch:
    return await database_sync_to_async_pool(claim_due_schedule_batch)(inputs.now, inputs.limit, after=inputs.after)


@activity.defn
async def acknowledge_schedule_activity(inputs: AcknowledgeScheduleInputs) -> bool:
    return await database_sync_to_async_pool(acknowledge_schedule)(inputs.occurrence, inputs.now)
