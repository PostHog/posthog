import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.data_imports.workflow_activities.emit_signals import (
    EmitSignalsActivityInputs,
    emit_data_import_signals_activity,
)


@workflow.defn(name="emit-data-import-signals")
class EmitDataImportSignalsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> EmitSignalsActivityInputs:
        loaded = json.loads(inputs[0])
        return EmitSignalsActivityInputs(**loaded)

    @workflow.run
    async def run(self, inputs: EmitSignalsActivityInputs) -> None:
        await workflow.execute_activity(
            emit_data_import_signals_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
