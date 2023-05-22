import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from temporalio import activity, workflow

from posthog.temporal.workflows.base import PostHogWorkflow


@dataclass
class NoopActivityArgs:
    time: str


@activity.defn
async def noop_activity(input: NoopActivityArgs) -> str:
    activity.logger.info(f"Running activity with parameter {input.time}")
    output = f"OK - {input.time}"
    logging.warning(f"[Action] - Action executed on worker with output: {output}")
    return output


@workflow.defn(name="no-op")
class NoOpWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> Any:
        """Parse inputs from the management command CLI.

        We expect only one input, so we just return it and assume it's correct.
        """
        if not inputs:
            # Preserving defaults from when this was the only workflow.
            inputs = [datetime.now().isoformat()]
        return inputs[0]

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
