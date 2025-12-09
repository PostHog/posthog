from pathlib import Path

from temporalio import activity

from posthog.models.exported_asset import ExportedAsset
from posthog.temporal.export_recording.types import ExportContext, ExportData, ExportRecordingInput


@activity.defn
async def build_recording_export_context(input: ExportRecordingInput) -> ExportContext:
    asset = await ExportedAsset.objects.select_related("team").aget(pk=input.exported_asset_id)

    if not (asset.export_context and asset.export_context.get("session_id")):
        raise RuntimeError("Malformed asset - must contain session_id")

    return ExportContext(
        team_id=asset.team.id,
        session_id=asset.export_context.get("session_id"),
    )


@activity.defn
async def export_clickhouse_rows(input: ExportContext) -> Path:
    pass


@activity.defn
async def export_recording_data(input: ExportContext) -> list[Path]:
    pass


@activity.defn
async def store_export_data(input: ExportData) -> None:
    pass


@activity.defn
async def cleanup_export_data(input: ExportData) -> None:
    pass
