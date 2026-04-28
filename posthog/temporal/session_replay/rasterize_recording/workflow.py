import json
import datetime as dt
from typing import Any

import temporalio.workflow as wf
from temporalio import common

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.search_attributes import POSTHOG_SESSION_RECORDING_ID_KEY

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
    def __init__(self) -> None:
        self._phase: str = "preparing"

    @wf.query
    def get_progress(self) -> dict[str, str]:
        """Coarse-grained phase of the rasterization workflow.

        Fine-grained frame progress is reported separately via activity
        heartbeats — read those via `describe().pending_activities`.
        """
        return {"phase": self._phase}

    @staticmethod
    def parse_inputs(inputs: list[str]) -> RasterizeRecordingInputs:
        return RasterizeRecordingInputs(**json.loads(inputs[0]))

    @wf.run
    async def run(self, inputs: RasterizeRecordingInputs) -> RasterizationActivityOutput:
        try:
            return await self._run(inputs)
        except Exception:
            # Only log on the terminal attempt — retries would double-count
            # recordings that fail-then-succeed.
            info = wf.info()
            retry_policy = info.retry_policy

            max_attempts = retry_policy.maximum_attempts if retry_policy else 1
            is_terminal = max_attempts is not None and max_attempts > 0 and info.attempt >= max_attempts

            if is_terminal:
                session_recording_id = info.typed_search_attributes.get(POSTHOG_SESSION_RECORDING_ID_KEY)
                wf.logger.warning(
                    "rasterize_recording.workflow_failed",
                    extra={
                        "session_recording_id": session_recording_id,
                        "exported_asset_id": inputs.exported_asset_id,
                        "phase": self._phase,
                    },
                )
            raise

    async def _run(self, inputs: RasterizeRecordingInputs) -> RasterizationActivityOutput:
        retry_policy = common.RetryPolicy(maximum_attempts=3)

        # Step 1: Read ExportedAsset, validate, build activity input
        self._phase = "preparing"
        activity_input: RasterizationActivityInput = await wf.execute_activity(
            build_rasterization_input,
            inputs.exported_asset_id,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        # Step 2: Dispatch rasterization to the Node.js worker
        # The Node.js activity returns a plain dict (cross-language boundary)
        self._phase = "rendering"
        raw_result: dict[str, Any] = await wf.execute_activity(
            "rasterize-recording",
            activity_input.model_dump(exclude_none=True),
            task_queue=settings.RASTERIZATION_TASK_QUEUE,
            start_to_close_timeout=dt.timedelta(minutes=30),
            heartbeat_timeout=dt.timedelta(seconds=30),
            retry_policy=common.RetryPolicy(maximum_attempts=2),
        )

        result = RasterizationActivityOutput.model_validate(raw_result)

        # Step 3: Finalize the ExportedAsset with the S3 URI and metadata
        self._phase = "finalizing"
        await wf.execute_activity(
            finalize_rasterization,
            FinalizeRasterizationInput(exported_asset_id=inputs.exported_asset_id, result=result),
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=retry_policy,
        )

        self._phase = "done"
        return result
