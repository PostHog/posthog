from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.utils import asyncify

from ..logic.sweeps import QUOTA_SWEEP_BATCH_SIZE, stop_runs_over_quota


@frozen
class StopRunsOverQuotaInputs:
    batch_size: int = QUOTA_SWEEP_BATCH_SIZE


@frozen
class StopRunsOverQuotaResult:
    cancelled: int


@activity.defn
@asyncify
def stop_cloud_agent_runs_over_quota_activity(inputs: StopRunsOverQuotaInputs) -> StopRunsOverQuotaResult:
    # Each cancel is a call to Temporal, so a full batch can take longer than the heartbeat timeout.
    with HeartbeaterSync():
        return StopRunsOverQuotaResult(cancelled=stop_runs_over_quota(batch_size=inputs.batch_size))
