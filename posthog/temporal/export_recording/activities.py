import re
from pathlib import Path
from urllib import parse

from temporalio import activity

from posthog.models.exported_asset import ExportedAsset
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.session_recording_v2_service import list_blocks
from posthog.storage import session_recording_v2_object_storage
from posthog.sync import database_sync_to_async
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.export_recording.types import ExportContext, ExportData, ExportRecordingInput

LOGGER = get_write_only_logger()


@activity.defn
async def build_recording_export_context(input: ExportRecordingInput) -> ExportContext:
    logger = LOGGER.bind()
    logger.info(f"Building export context for asset {input.exported_asset_id}")

    asset = await ExportedAsset.objects.select_related("team").aget(pk=input.exported_asset_id)

    logger.info(asset.export_context)

    if not (asset.export_context and asset.export_context.get("session_id")):
        raise RuntimeError("Malformed asset - must contain session_id")

    session_id = asset.export_context.get("session_id")
    logger.info(f"Built export context for session {session_id}")

    return ExportContext(
        team_id=asset.team.id,
        session_id=session_id,
    )


@activity.defn
async def export_clickhouse_rows(input: ExportContext) -> Path:
    pass


@activity.defn
async def export_recording_data(input: ExportContext) -> list[Path]:
    logger = LOGGER.bind()
    logger.info(f"Exporting recording data for session {input.session_id}")

    recording = SessionRecording(session_id=input.session_id, team_id=input.team_id)
    await database_sync_to_async(recording.load_metadata)()
    recording_blocks = await database_sync_to_async(list_blocks)(recording)

    logger.info(f"Found {len(recording_blocks)} blocks to export")

    recording_data: list[Path] = []

    for block in recording_blocks:
        _, _, s3_path, _, query, _ = parse.urlparse(block.url)
        s3_path = s3_path.lstrip("/")

        match = re.match(r"^range=bytes=(\d+)-(\d+)$", query)

        if not match:
            logger.warning(f"Got malformed byte range in block URL: {query}, skipping...")
            continue

        start_byte = int(match.group(1))

        try:
            async with session_recording_v2_object_storage.async_client() as storage:
                block_data = await storage.fetch_block_bytes(block.url)
            logger.info(f"Successfully fetched block data ({len(block_data)} bytes)")
        except session_recording_v2_object_storage.BlockFetchError:
            logger.warning(f"Failed to fetch block at {block.url}, skipping...")
            continue

        output_path = Path("/tmp") / s3_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("wb") as f:
            f.write(b"\x00" * start_byte)
            f.write(block_data)
            f.write(b"\x00" * 1024)

        logger.info(f"Wrote block data to {output_path}")
        recording_data.append(output_path)

    logger.info(f"Exported recording data to {len(recording_data)} files")
    return recording_data


@activity.defn
async def store_export_data(input: ExportData) -> None:
    pass


@activity.defn
async def cleanup_export_data(input: ExportData) -> None:
    pass
