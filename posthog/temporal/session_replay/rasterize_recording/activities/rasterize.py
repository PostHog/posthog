from django.conf import settings
from django.db import close_old_connections, transaction

import structlog
from temporalio import activity

from posthog.models.exported_asset import ExportedAsset
from posthog.storage import object_storage

from ..types import (
    BuildRasterizationResult,
    FinalizeRasterizationInput,
    InactivityPeriod,
    RasterizationActivityInput,
    RasterizationActivityOutput,
    compute_params_fingerprint,
)

logger = structlog.get_logger(__name__)

_RENDER_FINGERPRINT_KEY = "render_fingerprint"
_PERSISTED_OUTPUT_FIELDS: frozenset[str] = frozenset(
    {"video_duration_s", "playback_speed", "truncated", "file_size_bytes", "inactivity_periods"}
)


@activity.defn
def build_rasterization_input(exported_asset_id: int) -> BuildRasterizationResult:
    close_old_connections()

    asset = ExportedAsset.objects.select_related("team").get(pk=exported_asset_id)
    ctx = asset.export_context or {}

    session_id = ctx.get("session_recording_id")
    if not session_id:
        raise ValueError(f"ExportedAsset {exported_asset_id} has no session_recording_id in export_context")

    format_map = {"video/webm": "webm", "video/mp4": "mp4", "image/gif": "gif"}
    output_format = format_map.get(asset.export_format, "mp4")

    s3_key_prefix = f"{settings.OBJECT_STORAGE_EXPORTS_FOLDER}/{output_format}/team-{asset.team_id}/task-{asset.id}"

    # Callers may pass `timestamp`+`duration` or the native `start_offset_s`/`end_offset_s`.
    start_offset_s = ctx.get("start_offset_s") if ctx.get("start_offset_s") is not None else ctx.get("timestamp")
    duration = ctx.get("duration")
    end_offset_s = ctx.get("end_offset_s")
    if end_offset_s is None and duration is not None:
        end_offset_s = (start_offset_s or 0) + duration

    viewport_width = ctx.get("width")
    viewport_height = ctx.get("height")
    if viewport_width is not None:
        viewport_width = max(400, min(3840, int(viewport_width)))
    if viewport_height is not None:
        viewport_height = max(300, min(2160, int(viewport_height)))

    # 1x for short clips so output plays in real time; 4x for full sessions to cap file size.
    default_speed = 1 if (duration is not None and duration <= 5) else 4
    playback_speed = ctx.get("playback_speed", default_speed)

    activity_input = RasterizationActivityInput(
        team_id=asset.team_id,
        session_id=session_id,
        s3_bucket=settings.OBJECT_STORAGE_BUCKET,
        s3_key_prefix=s3_key_prefix,
        playback_speed=playback_speed,
        recording_fps=ctx.get("recording_fps", 24),
        trim=ctx.get("trim"),
        show_metadata_footer=ctx.get("show_metadata_footer", False),
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        start_offset_s=start_offset_s,
        end_offset_s=end_offset_s,
        output_format=output_format,
        skip_inactivity=ctx.get("skip_inactivity", True),
        mouse_tail=ctx.get("mouse_tail", True),
        max_virtual_time=ctx.get("max_virtual_time"),
    )

    fingerprint = compute_params_fingerprint(activity_input)

    cached = _try_synthesize_cached_output(asset, ctx, fingerprint)
    if cached is not None:
        return BuildRasterizationResult(cached_output=cached, render_fingerprint=fingerprint)

    return BuildRasterizationResult(activity_input=activity_input, render_fingerprint=fingerprint)


def _try_synthesize_cached_output(
    asset: ExportedAsset, ctx: dict, fingerprint: str
) -> RasterizationActivityOutput | None:
    if not asset.content_location:
        return None
    if ctx.get(_RENDER_FINGERPRINT_KEY) != fingerprint:
        return None
    # head_object returns None on 404 or any error — re-render in both cases.
    if object_storage.head_object(file_key=asset.content_location) is None:
        logger.info(
            "rasterize.cache.s3_missing_or_unreachable",
            asset_id=asset.id,
            content_location=asset.content_location,
        )
        return None

    missing_fields = [f for f in _PERSISTED_OUTPUT_FIELDS if f not in ctx]
    if missing_fields:
        logger.info(
            "rasterize.cache.export_context_missing_fields",
            asset_id=asset.id,
            missing_fields=missing_fields,
        )
        return None

    inactivity_periods = [InactivityPeriod.model_validate(p) for p in ctx.get("inactivity_periods") or []]

    return RasterizationActivityOutput(
        s3_uri=f"s3://{settings.OBJECT_STORAGE_BUCKET}/{asset.content_location}",
        video_duration_s=float(ctx["video_duration_s"]),
        playback_speed=float(ctx["playback_speed"]),
        show_metadata_footer=bool(ctx.get("show_metadata_footer", False)),
        truncated=bool(ctx["truncated"]),
        inactivity_periods=inactivity_periods,
        file_size_bytes=int(ctx["file_size_bytes"]),
    )


@activity.defn
def finalize_rasterization(inputs: FinalizeRasterizationInput) -> None:
    close_old_connections()
    result = inputs.result

    prefix = f"s3://{settings.OBJECT_STORAGE_BUCKET}/"
    if not result.s3_uri.startswith(prefix):
        raise ValueError(f"Unexpected s3_uri prefix: {result.s3_uri} (expected {prefix}...)")

    # Row lock serializes the JSONB read-modify-write against prep_session_video_asset_activity.
    with transaction.atomic():
        asset = ExportedAsset.objects.select_for_update().get(pk=inputs.exported_asset_id)
        asset.content_location = result.s3_uri[len(prefix) :]

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
        asset.export_context[_RENDER_FINGERPRINT_KEY] = inputs.render_fingerprint

        asset.save(update_fields=["content_location", "export_context"])

    logger.info(
        "rasterization_finalized",
        asset_id=asset.id,
        content_location=asset.content_location,
        video_duration_s=result.video_duration_s,
        file_size_bytes=result.file_size_bytes,
        render_fingerprint=inputs.render_fingerprint,
    )
