import math
import hashlib
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, model_validator

# Retry envelope for the Node rasterize activity (scheduled in workflow._run). Shared so the relayed
# recording-api token's TTL (rasterize.py) is derived from the same numbers and can't silently drift.
RASTERIZE_RENDER_TIMEOUT = timedelta(minutes=30)
RASTERIZE_RENDER_MAX_ATTEMPTS = 2

# Envelope for the whole workflow: the render's retry budget plus room for the prep and finalize
# activities and queue wait. The exports API uses this both as the workflow's execution_timeout and
# as the age at which it reports an export stuck, so the two can't drift and start calling a render
# that is still legitimately working a failure. A tighter caller timeout silently converts the second
# render attempt into an untyped WorkflowExecutionTimeout, bypassing error-code-based failure
# classification downstream.
RASTERIZE_WORKFLOW_TIMEOUT = RASTERIZE_RENDER_TIMEOUT * RASTERIZE_RENDER_MAX_ATTEMPTS + timedelta(minutes=15)

# execution_timeout that funds exactly one render attempt plus prep/finalize headroom, for callers
# with their own phase budget (the replay_vision sweep and evaluation). It still exceeds the render
# start-to-close, so a fast first failure leaves room to schedule a retry that fits the budget.
RASTERIZE_WORKFLOW_SINGLE_ATTEMPT_TIMEOUT = RASTERIZE_RENDER_TIMEOUT + timedelta(minutes=10)

# Every captured frame costs a beginFrame round-trip, a screenshot and an ffmpeg write, so the frame
# count is what decides whether a render finishes inside RASTERIZE_RENDER_TIMEOUT. Budget it from that
# timeout at a deliberately pessimistic per-frame cost, staying clear of the deadline so setup, upload
# and a heavy DOM still fit.
_ASSUMED_MS_PER_FRAME = 150
_RENDER_BUDGET_HEADROOM = 0.6
MAX_CAPTURE_FRAMES = int(
    RASTERIZE_RENDER_TIMEOUT.total_seconds() * 1000 * _RENDER_BUDGET_HEADROOM / _ASSUMED_MS_PER_FRAME
)

# Output frame rates to fall back through, highest first. A lower frame rate costs smoothness, while a
# higher speed costs the viewer's ability to follow the session, so frame rate gives way first.
_FPS_LADDER = (24, 15, 12, 10)
_FPS_FLOOR = _FPS_LADDER[-1]

# Past this, playback is too fast to follow, so it is only reached once frame rate has bottomed out.
_COMFORTABLE_PLAYBACK_SPEED = 8.0

# Short enough that speeding it up would leave nothing watchable.
REALTIME_CLIP_MAX_SECONDS = 5

# Beyond this, scaling stops helping: fitting the budget needs a speed at which each frame covers so
# much of the session that the video shows nothing useful. Exporting a chosen range is the answer for
# these, so the API refuses the whole-session export rather than returning something unwatchable.
MAX_EXPORTABLE_DURATION_SECONDS = 3 * 60 * 60
_DEFAULT_PLAYBACK_SPEED = 4.0
_DEFAULT_RECORDING_FPS = 24


class RenderRate(BaseModel, frozen=True):
    """The rate a recording is captured at.

    Named fields rather than a pair: both are numbers, and swapping them silently produces a render
    nobody asked for.
    """

    playback_speed: float
    recording_fps: int


def resolve_render_rate(rendered_span_s: float | None) -> RenderRate:
    """Pick a capture rate whose frame count fits the render budget.

    Frames are `span / playback_speed * recording_fps`, so a long recording at the defaults suited to a
    short one asks for more frames than any render can reach in time. Trading smoothness, and then
    speed, for a video that exists beats holding both fixed and producing nothing.

    `rendered_span_s` is wall time. Skipping inactivity means fewer frames than that implies, so this
    errs toward scaling slightly harder than strictly needed.
    """
    if rendered_span_s is None:
        return RenderRate(playback_speed=_DEFAULT_PLAYBACK_SPEED, recording_fps=_DEFAULT_RECORDING_FPS)

    if rendered_span_s <= REALTIME_CLIP_MAX_SECONDS:
        return RenderRate(playback_speed=1, recording_fps=_DEFAULT_RECORDING_FPS)

    for fps in _FPS_LADDER:
        required_speed = rendered_span_s * fps / MAX_CAPTURE_FRAMES
        if required_speed <= _COMFORTABLE_PLAYBACK_SPEED:
            return RenderRate(
                playback_speed=max(_DEFAULT_PLAYBACK_SPEED, math.ceil(required_speed)),
                recording_fps=fps,
            )

    # Long enough that even the lowest frame rate needs an uncomfortable speed. The alternative is a
    # render that never finishes, and the API refuses the recordings where this stops being watchable.
    return RenderRate(
        playback_speed=math.ceil(rendered_span_s * _FPS_FLOOR / MAX_CAPTURE_FRAMES),
        recording_fps=_FPS_FLOOR,
    )


class RasterizeRecordingInputs(BaseModel, frozen=True):
    """Input to the RasterizeRecordingWorkflow."""

    exported_asset_id: int
    product: Literal["session_replay", "replay_vision"] = "session_replay"


class RasterizationActivityInput(BaseModel, frozen=True):
    """Input sent to the Node.js rasterize-recording activity.

    Built by build_rasterization_input from the ExportedAsset's export_context.
    Field names use snake_case to match the TypeScript RasterizeRecordingInput interface.
    """

    session_id: str
    team_id: int
    # Team-scoped read token the rasterizer relays to recording-api (it cannot mint its own).
    # Defaults to "" so a workflow that recorded build_rasterization_input's result under an older
    # release (before this field existed) still deserializes on replay instead of failing validation.
    recording_api_token: str = ""
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


class RecordRasterizationFailureInput(BaseModel, frozen=True):
    """The renderer's own error code and message, resolved in the workflow before the activity runs.

    The code is the rasterizer's `RasterizationErrorCode`, which Temporal carries as the failure
    type. Without persisting it the reason lives only in workflow history, where neither the user nor
    a failure-rate breakdown can reach it.
    """

    exported_asset_id: int
    error_code: str
    error_message: str


# Output destination fields — excluded so bucket/prefix changes don't invalidate caches.
# recording_api_token is per-run and ephemeral, so it must never participate in the cache key.
_FINGERPRINT_EXCLUDE: set[str] = {"team_id", "session_id", "s3_bucket", "s3_key_prefix", "recording_api_token"}


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
