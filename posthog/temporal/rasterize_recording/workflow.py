import json
import datetime as dt
from typing import Any

import temporalio.workflow as wf
from temporalio import common

from posthog.temporal.common.base import PostHogWorkflow

with wf.unsafe.imports_passed_through():
    from django.conf import settings

from .activities import build_rasterization_input, finalize_rasterization
from .types import (
    FinalizeRasterizationInput,
    RasterizationActivityInput,
    RasterizationActivityOutput,
    RasterizeRecordingInputs,
)


@wf.defn(name="rasterize-recording")
class RasterizeRecordingWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RasterizeRecordingInputs:
        return RasterizeRecordingInputs(**json.loads(inputs[0]))

    @wf.run
    async def run(self, inputs: RasterizeRecordingInputs) -> RasterizationActivityOutput:
        retry_policy = common.RetryPolicy(maximum_attempts=3)

        # Step 1: Read ExportedAsset, validate, build activity input
        activity_input: RasterizationActivityInput = await wf.execute_activity(
            build_rasterization_input,
            inputs.exported_asset_id,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        # Step 2: Dispatch rasterization to the Node.js worker
        # The Node.js activity returns a plain dict (cross-language boundary)
        raw_result: dict[str, Any] = await wf.execute_activity(
            "rasterize-recording",
            activity_input.model_dump(exclude_none=True),
            task_queue=settings.RASTERIZATION_TASK_QUEUE,
            start_to_close_timeout=dt.timedelta(minutes=30),
            heartbeat_timeout=dt.timedelta(minutes=2),
            retry_policy=common.RetryPolicy(maximum_attempts=2),
        )

        result = RasterizationActivityOutput.model_validate(raw_result)

        # Step 3: Finalize the ExportedAsset with the S3 URI and metadata
        await wf.execute_activity(
            finalize_rasterization,
            FinalizeRasterizationInput(exported_asset_id=inputs.exported_asset_id, result=result),
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=retry_policy,
        )

        return result
