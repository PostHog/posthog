import json
import datetime as dt
from dataclasses import dataclass
from typing import Any

import temporalio.workflow as wf
from temporalio import common

from posthog.temporal.common.base import PostHogWorkflow  # matches repo conventions

from .activities import build_export_context_activity, record_and_persist_video_activity


@dataclass(frozen=True)
class VideoExportInputs:
    exported_asset_id: int
    use_puppeteer: bool = False


@wf.defn(name="export-video")
class VideoExportWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> VideoExportInputs:
        return VideoExportInputs(**json.loads(inputs[0]))

    @wf.run
    async def run(self, inputs: VideoExportInputs) -> None:
        retry_policy = common.RetryPolicy(maximum_attempts=3)
        build: dict[str, Any] = await wf.execute_activity(
            build_export_context_activity,
            inputs.exported_asset_id,
            start_to_close_timeout=dt.timedelta(seconds=300),
            retry_policy=retry_policy,
        )
        # Check if to use Playwright or Puppeteer, remove after fully switching to Puppeteer
        if inputs.use_puppeteer:
            build["use_puppeteer"] = True
        # Dynamic timeout: base 600s + recording duration + 30s buffer for processing
        recording_timeout = dt.timedelta(seconds=600 + build["duration"] + 30)
        await wf.execute_activity(
            record_and_persist_video_activity,
            build,
            start_to_close_timeout=recording_timeout,
            retry_policy=retry_policy,
        )
