import logging
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow


@dataclass
class NoopActivityArgs:
    time: str


@activity.defn
async def noop_activity(input: NoopActivityArgs) -> str:
    activity.logger.info(f"Running activity with parameter {input.time}")
    output = f"OK - {input.time}"
    logging.warning(f"[Action] - Action executed on worker with output: {output}")
    return output


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
        logging.warning(f"[Workflow] - Workflow executed on worker with output: {result}")
        return result
