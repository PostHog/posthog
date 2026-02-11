import os
import uuid
import datetime as dt
import tempfile
from typing import Any

from django.db import close_old_connections

import structlog
from temporalio import activity

from posthog.models.exported_asset import ExportedAsset, get_public_access_token, save_content_from_file
from posthog.tasks.exports.video_exporter import RecordReplayToFileOptions
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)


@activity.defn
def build_export_context_activity(exported_asset_id: int) -> dict[str, Any]:
    close_old_connections()
    asset = ExportedAsset.objects.select_related("team", "dashboard", "insight").get(pk=exported_asset_id)
    # recordings-only
    if not (asset.export_context and asset.export_context.get("session_recording_id")):
        raise RuntimeError("Video export supports session recordings only")

    access_token = get_public_access_token(asset, dt.timedelta(minutes=15))

    # Validate and sanitize timestamp
    ts_raw = asset.export_context.get("timestamp", 0)
    try:
        ts = max(0, int(float(ts_raw)))  # Ensure non-negative integer
    except (ValueError, TypeError):
        ts = 0

    # Validate CSS selector (basic sanitization)
    css_raw = asset.export_context.get("css_selector", ".replayer-wrapper")
    if not isinstance(css_raw, str) or len(css_raw) > 100:
        css = ".replayer-wrapper"  # Safe default
    else:
        css = css_raw.strip()

    # Validate duration
    duration = max(1, min(3600, int(asset.export_context.get("duration", 5))))  # 1-3600 seconds (1 hour max)

    # Get dimensions from frontend (will be None if not set)
    width = asset.export_context.get("width")
    height = asset.export_context.get("height")

    # Apply bounds if dimensions are provided
    if width is not None:
        width = max(400, min(3840, int(width)))
    if height is not None:
        height = max(300, min(2160, int(height)))

    # Display additional metadata for LLMs in the video
    show_metadata_footer = asset.export_context.get("show_metadata_footer", False)

    # we can set playback speed to any integer between 1 and 360
    try:
        playback_speed = max(1, min(360, int(asset.export_context.get("playback_speed", 1))))
    except (ValueError, TypeError):
        playback_speed = 1

    url_params = {
        "token": access_token,
        "t": ts,
        "fullscreen": "true",
        "inspectorSideBar": "false",
        "showInspector": "false",
    }
    if playback_speed != 1:
        url_params["playerSpeed"] = playback_speed
    if show_metadata_footer:
        url_params["showMetadataFooter"] = "true"

    url = absolute_uri(f"/exporter?{'&'.join(f'{key}={value}' for key, value in url_params.items())}")

    fmt = asset.export_format
    tmp_ext = "mp4" if fmt == "video/mp4" else "gif" if fmt == "image/gif" else "webm"
    return {
        "exported_asset_id": exported_asset_id,
        "url_to_render": url,
        "css_selector": css,
        "width": width,
        "height": height,
        "export_format": fmt,
        "tmp_ext": tmp_ext,
        "duration": duration,
        "playback_speed": playback_speed,
    }


@activity.defn
def record_and_persist_video_activity(build: dict[str, Any]) -> None:
    """Record replay to file and persist in a single activity. Must run on same worker
    so the temp file exists—passing paths between activities fails when they run on
    different workers (different /tmp filesystems)."""
    from posthog.tasks.exports.video_exporter import record_replay_to_file

    close_old_connections()
    asset = ExportedAsset.objects.select_related("team").get(pk=build["exported_asset_id"])

    with tempfile.TemporaryDirectory(prefix="ph-video-export-") as tmp_dir:
        tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4()}.{build['tmp_ext']}")
        inactivity_periods = record_replay_to_file(
            RecordReplayToFileOptions(
                image_path=tmp_path,
                url_to_render=build["url_to_render"],
                screenshot_width=build.get("width"),
                wait_for_css_selector=build["css_selector"],
                screenshot_height=build.get("height"),
                recording_duration=build["duration"],
                playback_speed=build.get("playback_speed", 1),
                use_puppeteer=build.get("use_puppeteer", False),
            ),
        )
        if inactivity_periods:
            if asset.export_context is None:
                asset.export_context = {}
            asset.export_context["inactivity_periods"] = [x.model_dump() for x in inactivity_periods]
            asset.save(update_fields=["export_context"])
        # Check file size first to prevent OOM
        file_size = os.path.getsize(tmp_path)
        MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB limit
        if file_size > MAX_FILE_SIZE:
            raise RuntimeError(
                f"Video file too large: {file_size / (1024 * 1024):.1f}MB exceeds {MAX_FILE_SIZE // (1024 * 1024)}MB limit"
            )
        save_content_from_file(asset, tmp_path)
