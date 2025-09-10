import os
import uuid
import shutil
import datetime as dt
import tempfile
from typing import Any

from django.db import close_old_connections

import structlog
from temporalio import activity

from posthog.models.exported_asset import ExportedAsset, get_public_access_token, save_content
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

    url = absolute_uri(
        f"/exporter?token={access_token}&t={ts}&fullscreen=true&inspectorSideBar=false&showInspector=false"
    )

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

    fmt = asset.export_format
    tmp_ext = "mp4" if fmt == "video/mp4" else "gif" if fmt == "image/gif" else "webm"
    return {
        "url_to_render": url,
        "css_selector": css,
        "width": width,
        "height": height,
        "export_format": fmt,
        "tmp_ext": tmp_ext,
        "duration": duration,
    }


@activity.defn
def record_replay_video_activity(build: dict[str, Any]) -> dict[str, Any]:
    from posthog.tasks.exports.video_exporter import record_replay_to_file

    tmp_dir = tempfile.mkdtemp(prefix="ph-video-export-")
    tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4()}.{build['tmp_ext']}")
    try:
        record_replay_to_file(
            image_path=tmp_path,
            url_to_render=build["url_to_render"],
            screenshot_width=build.get("width"),  # None if not provided
            wait_for_css_selector=build["css_selector"],
            screenshot_height=build.get("height"),  # None if not provided
            recording_duration=build["duration"],
        )
        return {"tmp_path": tmp_path}
    except Exception:
        # Clean up temp directory on failure
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


@activity.defn
def persist_exported_asset_activity(inputs: dict[str, Any]) -> None:
    close_old_connections()
    asset = ExportedAsset.objects.select_related("team").get(pk=inputs["exported_asset_id"])
    tmp_path = inputs["tmp_path"]

    # Check file size first to prevent OOM
    file_size = os.path.getsize(tmp_path)
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB limit
    if file_size > MAX_FILE_SIZE:
        raise RuntimeError(
            f"Video file too large: {file_size / (1024*1024):.1f}MB exceeds {MAX_FILE_SIZE // (1024*1024)}MB limit"
        )

    # Read in chunks to avoid loading entire file into memory at once
    chunk_size = 64 * 1024  # 64KB chunks for better I/O performance
    chunks = []
    with open(tmp_path, "rb") as f:
        while chunk := f.read(chunk_size):
            chunks.append(chunk)

    data = b"".join(chunks)
    save_content(asset, data)

    # Cleanup
    try:
        os.remove(tmp_path)
        shutil.rmtree(os.path.dirname(tmp_path), ignore_errors=True)
    except Exception:
        pass
