"""Wall-clock estimates for session replay video rasterization.

Keep RASTERIZE_ACTIVITY_TIMEOUT_S in sync with start_to_close_timeout on the
rasterize-recording activity in workflow.py.
"""

from __future__ import annotations

RASTERIZE_ACTIVITY_TIMEOUT_S = 30 * 60

# Empirical capture throughput from prod recording-rasterizer (frames / wall second).
_ESTIMATED_CAPTURE_FPS = 30

SKIP_INACTIVITY_AUTO_ADJUSTED_KEY = "skip_inactivity_auto_adjusted"
SKIP_INACTIVITY_ADJUSTMENT_MESSAGE_KEY = "skip_inactivity_adjustment_message"

SKIP_INACTIVITY_ADJUSTMENT_MESSAGE = (
    "This recording is too long to export with idle time included within the render "
    "time limit. Idle periods were skipped automatically so the export can finish."
)


def clip_duration_s(
    *,
    start_offset_s: float | None,
    end_offset_s: float | None,
    duration: float | None,
) -> float | None:
    if start_offset_s is not None and end_offset_s is not None:
        return max(0.0, end_offset_s - start_offset_s)
    if duration is not None:
        return float(duration)
    return None


def estimate_rasterize_wall_time_s(
    *,
    content_duration_s: float,
    recording_fps: int = 24,
    estimated_capture_fps: float = _ESTIMATED_CAPTURE_FPS,
) -> float:
    """Estimate wall seconds to capture content_duration_s of session replay.

    Matches Node estimateTotalFrames: frames ≈ content_duration_s * recording_fps,
    then divide by observed capture throughput.
    """
    if content_duration_s <= 0:
        return 0.0
    estimated_frames = content_duration_s * recording_fps
    return estimated_frames / estimated_capture_fps


def apply_skip_inactivity_timeout_guard(
    export_context: dict,
    *,
    session_duration_s: float | None,
    active_seconds_s: float | None,
    activity_timeout_s: float = RASTERIZE_ACTIVITY_TIMEOUT_S,
) -> tuple[bool, dict[str, object]]:
    """Return skip_inactivity and export_context patches when a full export would time out."""
    if export_context.get("skip_inactivity", True):
        return bool(export_context.get("skip_inactivity", True)), {}

    if session_duration_s is None or session_duration_s <= 0:
        return False, {}

    recording_fps = int(export_context.get("recording_fps") or 24)

    full_wall_s = estimate_rasterize_wall_time_s(
        content_duration_s=session_duration_s,
        recording_fps=recording_fps,
    )
    if full_wall_s <= activity_timeout_s:
        return False, {}

    active_duration_s = active_seconds_s if active_seconds_s is not None else session_duration_s
    active_wall_s = estimate_rasterize_wall_time_s(
        content_duration_s=active_duration_s,
        recording_fps=recording_fps,
    )

    patches: dict[str, object] = {
        "skip_inactivity": True,
        SKIP_INACTIVITY_AUTO_ADJUSTED_KEY: True,
        SKIP_INACTIVITY_ADJUSTMENT_MESSAGE_KEY: SKIP_INACTIVITY_ADJUSTMENT_MESSAGE,
    }

    if active_wall_s > activity_timeout_s:
        patches[SKIP_INACTIVITY_ADJUSTMENT_MESSAGE_KEY] = (
            "This recording is too long to export fully within the render time limit. "
            "Idle periods were skipped, but the export may still time out."
        )

    return True, patches


def adjust_replay_export_context_for_timeout(
    export_context: dict,
    *,
    team_id: int,
    session_duration_s: float | None = None,
    active_seconds_s: float | None = None,
) -> dict:
    """Merge skip_inactivity timeout guard patches into export_context when needed."""
    session_id = export_context.get("session_recording_id")
    if not session_id:
        return export_context

    start_offset_s = (
        export_context.get("start_offset_s")
        if export_context.get("start_offset_s") is not None
        else export_context.get("timestamp")
    )
    end_offset_s = export_context.get("end_offset_s")
    duration = export_context.get("duration")
    if end_offset_s is None and duration is not None:
        end_offset_s = (start_offset_s or 0) + duration

    clip_s = clip_duration_s(
        start_offset_s=float(start_offset_s) if start_offset_s is not None else None,
        end_offset_s=float(end_offset_s) if end_offset_s is not None else None,
        duration=float(duration) if duration is not None else None,
    )
    resolved_session_duration_s = session_duration_s if session_duration_s is not None else clip_s
    if resolved_session_duration_s is None:
        return export_context

    _, patches = apply_skip_inactivity_timeout_guard(
        export_context,
        session_duration_s=resolved_session_duration_s,
        active_seconds_s=active_seconds_s,
    )
    if not patches:
        return export_context

    return {**export_context, **patches}
