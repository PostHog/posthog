import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow

from posthog.batch_exports.service import BackfillDetails, NoOpInputs
from posthog.temporal.common.base import PostHogWorkflow


@dataclass
class NoopActivityArgs:
    arg: str
    backfill_details: BackfillDetails | None = None


@activity.defn
async def noop_activity(inputs: NoopActivityArgs) -> str:
    activity.logger.info(f"Running activity with parameter {inputs.arg}")
    output = f"OK - {inputs.arg}"
    logging.warning(f"[Action] - Action executed on worker with output: {output}")
    return output


@workflow.defn(name="no-op")
class NoOpWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> Any:
        """Parse inputs from the management command CLI.

        We expect only one input, so we just return it and assume it's correct.
        """
        loaded = json.loads(inputs[0])
        return NoOpInputs(**loaded)

    @workflow.run
    async def run(self, inputs: NoOpInputs) -> str:
        workflow.logger.info(f"Running workflow with parameter {inputs.arg}")
        result = await workflow.execute_activity(
            noop_activity,
            NoopActivityArgs(inputs.arg, inputs.backfill_details),
            start_to_close_timeout=timedelta(seconds=60),
            schedule_to_close_timeout=timedelta(minutes=5),
        )
        logging.warning(f"[Workflow] - Workflow executed on worker with output: {result}")
        return result
