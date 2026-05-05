from posthog.temporal.session_replay.rasterize_recording.activities import (
    build_rasterization_input,
    bump_stuck_counter_activity,
    clear_stuck_counter_activity,
    finalize_rasterization,
)
from posthog.temporal.session_replay.rasterize_recording.workflow import RasterizeRecordingWorkflow

RASTERIZE_RECORDING_WORKFLOWS = [RasterizeRecordingWorkflow]
RASTERIZE_RECORDING_ACTIVITIES = [
    build_rasterization_input,
    finalize_rasterization,
    bump_stuck_counter_activity,
    clear_stuck_counter_activity,
]
