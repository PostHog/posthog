from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow


@dataclass
class NoopActivityArgs:
    time: str


@activity.defn
async def noop_activity(input: NoopActivityArgs) -> str:
    activity.logger.info(f"Running activity with parameter {input.time}")
    return f"OK - {input.time}"


@workflow.defn
class NoOpWorkflow:
    @workflow.run
    async def run(self, time: str) -> str:
        workflow.logger.info(f"Running workflow with parameter {time}")
        result = await workflow.execute_activity(
            noop_activity,
            NoopActivityArgs(time),
            start_to_close_timeout=timedelta(seconds=60),
            schedule_to_close_timeout=timedelta(minutes=5),
        )
        return result
