import hashlib
from typing import Literal

from pydantic import BaseModel, model_validator


class RasterizeRecordingInputs(BaseModel, frozen=True):
    """Input to the RasterizeRecordingWorkflow."""

    exported_asset_id: int


class RasterizationActivityInput(BaseModel, frozen=True):
    """Input sent to the Node.js rasterize-recording activity.

    Built by build_rasterization_input from the ExportedAsset's export_context.
    Field names use snake_case to match the TypeScript RasterizeRecordingInput interface.
    """

    session_id: str
    team_id: int
    s3_bucket: str
    s3_key_prefix: str
    playback_speed: float = 4
    recording_fps: int = 24
    trim: float | None = None
    max_virtual_time: float | None = None
    show_metadata_footer: bool = False
    viewport_width: int | None = None
    viewport_height: int | None = None
    start_offset_s: float | None = None
    end_offset_s: float | None = None
    output_format: Literal["mp4", "webm", "gif"] = "mp4"
    skip_inactivity: bool = True
    mouse_tail: bool = True


class InactivityPeriod(BaseModel, frozen=True):
    ts_from_s: float
    ts_to_s: float | None = None
    active: bool = True
    recording_ts_from_s: float | None = None
    recording_ts_to_s: float | None = None


class ActivityTimings(BaseModel, frozen=True):
    total_s: float = 0
    setup_s: float = 0
    capture_s: float = 0
    upload_s: float = 0


class RasterizationActivityOutput(BaseModel, frozen=True):
    """Output from the Node.js rasterize-recording activity.

    Field names match the TypeScript RasterizeRecordingOutput interface.
    """

    s3_uri: str
    video_duration_s: float
    playback_speed: float
    show_metadata_footer: bool = False
    truncated: bool = False
    inactivity_periods: list[InactivityPeriod] = []
    file_size_bytes: int = 0
    timings: ActivityTimings = ActivityTimings()


class FinalizeRasterizationInput(BaseModel, frozen=True):
    exported_asset_id: int
    result: RasterizationActivityOutput
    render_fingerprint: str


# Output destination fields — excluded so bucket/prefix changes don't invalidate caches.
_FINGERPRINT_EXCLUDE: set[str] = {"team_id", "session_id", "s3_bucket", "s3_key_prefix"}


def compute_params_fingerprint(activity_input: "RasterizationActivityInput") -> str:
    payload = activity_input.model_dump_json(exclude=_FINGERPRINT_EXCLUDE)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class BuildRasterizationResult(BaseModel, frozen=True):
    activity_input: RasterizationActivityInput | None = None
    cached_output: RasterizationActivityOutput | None = None
    render_fingerprint: str

    @model_validator(mode="after")
    def _exactly_one(self) -> "BuildRasterizationResult":
        if (self.activity_input is None) == (self.cached_output is None):
            raise ValueError("Exactly one of activity_input/cached_output must be set")
        return self
