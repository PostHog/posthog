from pathlib import Path

from temporalio import activity

from posthog.temporal.export_recording.types import ExportContext, ExportData, ExportRecordingInput


@activity.defn
async def build_recording_export_context(input: ExportRecordingInput) -> ExportContext:
    pass


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
