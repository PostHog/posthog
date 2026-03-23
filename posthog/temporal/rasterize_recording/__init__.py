from .activities import build_rasterization_input, finalize_rasterization
from .workflow import RasterizeRecordingWorkflow

WORKFLOWS = [RasterizeRecordingWorkflow]
ACTIVITIES = [
    build_rasterization_input,
    finalize_rasterization,
]
