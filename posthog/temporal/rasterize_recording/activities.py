from django.conf import settings
from django.db import close_old_connections

import structlog
from temporalio import activity

from posthog.models.exported_asset import ExportedAsset

from .types import FinalizeRasterizationInput, RasterizationActivityInput

logger = structlog.get_logger(__name__)


@activity.defn
def build_rasterization_input(exported_asset_id: int) -> RasterizationActivityInput:
    """Read an ExportedAsset row, validate it, and build the rasterization activity input."""
    close_old_connections()

    asset = ExportedAsset.objects.select_related("team").get(pk=exported_asset_id)
    ctx = asset.export_context or {}

    session_id = ctx.get("session_recording_id")
    if not session_id:
        raise ValueError(f"ExportedAsset {exported_asset_id} has no session_recording_id in export_context")

    s3_key_prefix = f"{settings.OBJECT_STORAGE_EXPORTS_FOLDER}/mp4/team-{asset.team_id}/task-{asset.id}"

    return RasterizationActivityInput(
        team_id=asset.team_id,
        session_id=session_id,
        s3_bucket=settings.OBJECT_STORAGE_BUCKET,
        s3_key_prefix=s3_key_prefix,
        playback_speed=ctx.get("playback_speed", 4),
        recording_fps=ctx.get("recording_fps", 24),
        trim=ctx.get("trim"),
        show_metadata_footer=ctx.get("show_metadata_footer", False),
        viewport_width=ctx.get("width"),
        viewport_height=ctx.get("height"),
        start_timestamp=ctx.get("start_timestamp"),
        end_timestamp=ctx.get("end_timestamp"),
        skip_inactivity=ctx.get("skip_inactivity", True),
        mouse_tail=ctx.get("mouse_tail", True),
        capture_timeout=ctx.get("capture_timeout"),
    )


@activity.defn
def finalize_rasterization(inputs: FinalizeRasterizationInput) -> None:
    """Update the ExportedAsset with the S3 location and rasterization metadata."""
    close_old_connections()

    asset = ExportedAsset.objects.get(pk=inputs.exported_asset_id)
    result = inputs.result

    # Extract the object path from the s3_uri (strip "s3://{bucket}/" prefix)
    # e.g. "s3://posthog/exports/mp4/team-1/task-123/uuid.mp4" -> "exports/mp4/team-1/task-123/uuid.mp4"
    prefix = f"s3://{settings.OBJECT_STORAGE_BUCKET}/"
    if not result.s3_uri.startswith(prefix):
        raise ValueError(f"Unexpected s3_uri prefix: {result.s3_uri} (expected {prefix}...)")

    asset.content_location = result.s3_uri[len(prefix) :]

    # Store rasterization metadata in export_context
    if asset.export_context is None:
        asset.export_context = {}
    asset.export_context.update(
        result.model_dump(
            include={
                "video_duration_s",
                "playback_speed",
                "truncated",
                "file_size_bytes",
                "inactivity_periods",
            }
        )
    )

    asset.save(update_fields=["content_location", "export_context"])

    logger.info(
        "rasterization_finalized",
        asset_id=asset.id,
        content_location=asset.content_location,
        video_duration_s=result.video_duration_s,
        file_size_bytes=result.file_size_bytes,
    )
