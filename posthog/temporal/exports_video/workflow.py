import datetime as dt
import temporalio.workflow as wf
from temporalio import common
from dataclasses import dataclass
from posthog.temporal.common.base import PostHogWorkflow  # matches repo conventions

from .activities import (
    build_export_context_activity,
    record_replay_video_activity,
    persist_exported_asset_activity,
)


@dataclass(frozen=True)
class VideoExportInputs:
    exported_asset_id: int


@wf.defn(name="export-video")
class VideoExportWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> VideoExportInputs:
        import json

        return VideoExportInputs(**json.loads(inputs[0]))

    @wf.run
    async def run(self, inputs: VideoExportInputs) -> None:
        ctx = {"retry_policy": common.RetryPolicy(maximum_attempts=3)}
        build = await wf.execute_activity(
            build_export_context_activity,
            inputs.exported_asset_id,
            start_to_close_timeout=dt.timedelta(seconds=30),
            **ctx,
        )
        # build = { url_to_render, css_selector, width, height, export_format, tmp_ext }

        rec = await wf.execute_activity(
            record_replay_video_activity,
            build,
            start_to_close_timeout=dt.timedelta(minutes=2),
            **ctx,
        )
        # rec = { tmp_path } – path to mp4/gif/webm ready file

        await wf.execute_activity(
            persist_exported_asset_activity,
            {"exported_asset_id": inputs.exported_asset_id, "tmp_path": rec["tmp_path"]},
            start_to_close_timeout=dt.timedelta(seconds=30),
            **ctx,
        )
