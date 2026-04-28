from posthog.temporal.session_replay.rasterize_recording.activities import (
    build_rasterization_input,
    finalize_rasterization,
)
from posthog.temporal.session_replay.rasterize_recording.workflow import RasterizeRecordingWorkflow

WORKFLOWS = [RasterizeRecordingWorkflow]
ACTIVITIES = [
    build_rasterization_input,
    finalize_rasterization,
]
