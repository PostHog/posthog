import json
import datetime as dt
from dataclasses import dataclass
from typing import Any

import temporalio.workflow as wf
from temporalio import common

from posthog.temporal.common.base import PostHogWorkflow  # matches repo conventions

from .activities import build_export_context_activity, persist_exported_asset_activity, record_replay_video_activity


@dataclass(frozen=True)
class VideoExportInputs:
    exported_asset_id: int


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
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=retry_policy,
        )
        # build = { url_to_render, css_selector, width, height, export_format, tmp_ext }

        # Dynamic timeout: base 60s + recording duration + 30s buffer for processing
        recording_timeout = dt.timedelta(seconds=60 + build["duration"] + 30)
        rec: dict[str, Any] = await wf.execute_activity(
            record_replay_video_activity,
            build,
            start_to_close_timeout=recording_timeout,
            retry_policy=retry_policy,
        )
        # rec = { tmp_path } – path to mp4/gif/webm ready file

        await wf.execute_activity(
            persist_exported_asset_activity,
            {"exported_asset_id": inputs.exported_asset_id, "tmp_path": rec["tmp_path"]},
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=retry_policy,
        )
