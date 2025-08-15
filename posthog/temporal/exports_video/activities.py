import os
import uuid
import tempfile
import shutil
from typing import Any
from temporalio import activity
import datetime as dt

from posthog.models.exported_asset import ExportedAsset, get_public_access_token, save_content
from posthog.utils import absolute_uri

# Optional: stable browser cache for Playwright worker processes
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.join("/tmp", "ms-playwright"))


@activity.defn
def build_export_context_activity(exported_asset_id: int) -> dict[str, Any]:
    asset = ExportedAsset.objects.select_related("team", "dashboard", "insight").get(pk=exported_asset_id)
    # recordings-only
    if not (asset.export_context and asset.export_context.get("session_recording_id")):
        raise RuntimeError("Video export supports session recordings only")

    access_token = get_public_access_token(asset, dt.timedelta(minutes=15))
    ts = asset.export_context.get("timestamp") or 0
    url = absolute_uri(f"/exporter?token={access_token}&t={ts}&fullscreen=true")
    css = asset.export_context.get("css_selector", ".replayer-wrapper")
    width = int(asset.export_context.get("width", 1400))
    height = int(asset.export_context.get("height", 600))

    fmt = asset.export_format
    tmp_ext = "mp4" if fmt == "video/mp4" else "gif" if fmt == "image/gif" else "webm"
    return {
        "url_to_render": url,
        "css_selector": css,
        "width": width,
        "height": height,
        "export_format": fmt,
        "tmp_ext": tmp_ext,
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
            screenshot_width=build["width"],
            wait_for_css_selector=build["css_selector"],
            screenshot_height=build["height"],
        )
        return {"tmp_path": tmp_path}
    except Exception:
        # Clean up temp directory on failure
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


@activity.defn
def persist_exported_asset_activity(inputs: dict[str, Any]) -> None:
    asset = ExportedAsset.objects.select_related("team").get(pk=inputs["exported_asset_id"])
    tmp_path = inputs["tmp_path"]
    with open(tmp_path, "rb") as f:
        data = f.read()
    save_content(asset, data)
    try:
        os.remove(tmp_path)
        shutil.rmtree(os.path.dirname(tmp_path), ignore_errors=True)
    except Exception:
        pass
