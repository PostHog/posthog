from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import close_old_connections, transaction

import structlog
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.ph_client import ph_background_capture
from posthog.session_recordings.recordings.recording_api_jwt import mint_recording_api_token, recording_api_jwt_enabled
from posthog.storage import object_storage

from products.exports.backend.analytics import capture_export_event
from products.exports.backend.models.exported_asset import ExportedAsset, is_valid_session_recording_id
from products.exports.backend.source_authentication import assert_export_authorization

from ..types import (
    RASTERIZE_RENDER_MAX_ATTEMPTS,
    RASTERIZE_RENDER_TIMEOUT,
    BuildRasterizationResult,
    FinalizeRasterizationInput,
    InactivityPeriod,
    RasterizationActivityInput,
    RasterizationActivityOutput,
    compute_params_fingerprint,
)

logger = structlog.get_logger(__name__)

# The rasterizer relays one token across an entire render and cannot re-mint, so it must outlive the
# whole Node activity envelope. Derive the lifetime from the activity's actual retry envelope (shared
# constants in ..types) plus a 1h buffer for queue wait/backoff, so bumping the retry policy can't
# silently leave the token expiring mid-render. Still a read-only, single-team token (a big
# improvement over the unscoped shared secret it replaces).
_RASTERIZE_TOKEN_TTL = RASTERIZE_RENDER_TIMEOUT * RASTERIZE_RENDER_MAX_ATTEMPTS + timedelta(hours=1)

_RENDER_FINGERPRINT_KEY = "render_fingerprint"

# Fields cleared when a render succeeds, so a row that failed and was re-rendered doesn't keep
# showing the old reason next to its content.
_FAILURE_FIELDS = ["exception", "exception_type", "failure_type"]
_PERSISTED_OUTPUT_FIELDS: frozenset[str] = frozenset(
    {"video_duration_s", "playback_speed", "truncated", "file_size_bytes", "inactivity_periods"}
)


def report_export_event(asset: ExportedAsset, event: str, **properties: Any) -> None:
    """Report an export lifecycle event through the client suited to a long-lived worker."""
    capture_export_event(asset, event, ph_background_capture(), **properties)


@activity.defn
def build_rasterization_input(exported_asset_id: int) -> BuildRasterizationResult:
    close_old_connections()

    asset = ExportedAsset.objects.select_related("team__organization", "created_by").get(pk=exported_asset_id)
    try:
        assert_export_authorization(asset)
    except ValueError as error:
        raise ApplicationError(str(error), non_retryable=True) from error
    ctx = asset.export_context or {}

    session_id = ctx.get("session_recording_id")
    if not session_id:
        # non_retryable: the asset's export_context is permanently invalid; retrying re-reads the
        # same row, and the eventual workflow failure would wrongly mark the session as stuck.
        raise ApplicationError(
            f"ExportedAsset {exported_asset_id} has no session_recording_id in export_context", non_retryable=True
        )
    # Assets reach this activity from several writers, not all of them behind the exports serializer,
    # so the id is re-checked here before it becomes part of an internal recording API path.
    if not is_valid_session_recording_id(session_id):
        # Logged as well as raised so a session id we reject wrongly is greppable, not just a failed render.
        logger.warning("rasterize.malformed_session_recording_id", asset_id=exported_asset_id)
        raise ApplicationError(
            f"ExportedAsset {exported_asset_id} has a malformed session_recording_id", non_retryable=True
        )

    output_format = ExportedAsset.RASTERIZED_FORMATS.get(asset.export_format, "mp4")

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

    # The output video is always real-time (the ffmpeg setpts filter undoes the speed-up); speed
    # only reduces the virtual time a render spends playing the session. 1x for short clips keeps
    # capture simple; 4x for full sessions bounds virtual time on long recordings.
    default_speed = 1 if (duration is not None and duration <= 5) else 4
    # `or` rather than a .get default so an explicit null in export_context also falls back instead
    # of failing pydantic validation three retries in a row.
    playback_speed = ctx.get("playback_speed") or default_speed
    recording_fps = ctx.get("recording_fps") or 24
    # Clamp the render rate so a large fps × speed product can't exhaust the shared rasterizer pool.
    # The lower bound matches Node's validateInput: speeds below 1 have no slow-motion filter chain
    # and would misreport the video duration.
    playback_speed = max(1.0, min(360.0, float(playback_speed)))
    recording_fps = min(60, int(recording_fps))

    # Empty until the signing secret is configured; the rasterizer then relays the legacy shared
    # secret instead, so rollout can happen per environment without breaking rendering.
    recording_api_token = (
        mint_recording_api_token(asset.team_id, "read", ttl=_RASTERIZE_TOKEN_TTL) if recording_api_jwt_enabled() else ""
    )

    activity_input = RasterizationActivityInput(
        team_id=asset.team_id,
        session_id=session_id,
        recording_api_token=recording_api_token,
        s3_bucket=settings.OBJECT_STORAGE_BUCKET,
        s3_key_prefix=s3_key_prefix,
        playback_speed=playback_speed,
        recording_fps=recording_fps,
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
        # A cache hit returns straight to the workflow without reaching finalize_rasterization, so
        # this is the only place it can report an outcome. Both events fire so started/succeeded
        # counts stay comparable.
        report_export_event(asset, "export started", cached=True)
        report_export_event(asset, "export succeeded", cached=True)
        return BuildRasterizationResult(cached_output=cached, render_fingerprint=fingerprint)

    report_export_event(
        asset,
        "export started",
        playback_speed=playback_speed,
        recording_fps=recording_fps,
        output_format=output_format,
    )

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
        asset = (
            ExportedAsset.objects.select_related("team__organization", "created_by")
            .select_for_update(of=("self",))
            .get(pk=inputs.exported_asset_id)
        )
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

        asset.exception = None
        asset.exception_type = None
        asset.failure_type = None

        asset.save(update_fields=["content_location", "export_context", *_FAILURE_FIELDS])

    logger.info(
        "rasterization_finalized",
        asset_id=asset.id,
        content_location=asset.content_location,
        video_duration_s=result.video_duration_s,
        file_size_bytes=result.file_size_bytes,
        render_fingerprint=inputs.render_fingerprint,
    )

    report_export_event(
        asset,
        "export succeeded",
        cached=False,
        duration_ms=round(result.timings.total_s * 1000, 2),
        video_duration_s=result.video_duration_s,
        file_size_bytes=result.file_size_bytes,
        truncated=result.truncated,
    )
