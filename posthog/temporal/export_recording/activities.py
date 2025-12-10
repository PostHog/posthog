import re
import uuid
import shutil
from datetime import datetime
from pathlib import Path
from urllib import parse
from uuid import uuid4

import pytz
from temporalio import activity

from posthog.models.exported_asset import ExportedAsset
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.session_recording_v2_service import list_blocks
from posthog.storage import session_recording_v2_object_storage
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.export_recording.types import ExportContext, ExportRecordingInput

LOGGER = get_write_only_logger()


@activity.defn
async def build_recording_export_context(input: ExportRecordingInput) -> ExportContext:
    logger = LOGGER.bind()
    logger.info(f"Building export context for asset {input.exported_asset_id}")

    asset = await ExportedAsset.objects.select_related("team").aget(pk=input.exported_asset_id)

    if not (asset.export_context and asset.export_context.get("session_id")):
        raise RuntimeError("Malformed asset - must contain session_id")

    session_id = asset.export_context.get("session_id")
    logger.info(f"Built export context for session {session_id}")

    return ExportContext(
        export_id=uuid.uuid4(),
        exported_asset_id=input.exported_asset_id,
        session_id=session_id,
        team_id=asset.team.id,
    )


@activity.defn
async def export_replay_clickhouse_rows(input: ExportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Exporting Replay ClickHouse rows for session {input.session_id}")

    query: str = SessionReplayEvents.get_metadata_query(format="JSON")
    parameters = {
        "team_id": input.team_id,
        "session_id": input.session_id,
        "python_now": datetime.now(pytz.timezone("UTC")),
    }

    ch_query_id = str(uuid4())
    logger.info(f"Querying ClickHouse with query_id: {ch_query_id}")

    raw_response: bytes = b""
    async with get_client() as client:
        async with client.aget_query(query=query, query_parameters=parameters, query_id=ch_query_id) as ch_response:
            raw_response = await ch_response.content.read()

    logger.info(f"Received {len(raw_response)} bytes from ClickHouse")

    output_path = Path("/tmp") / str(input.export_id) / "clickhouse" / "session-replay-events.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("wb") as f:
        f.write(raw_response)

    logger.info(f"Wrote replay ClickHouse metadata to {output_path}")


@activity.defn
async def export_event_clickhouse_rows(input: ExportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Exporting event ClickHouse rows for session {input.session_id}")

    query: str = """
        SELECT * EXCEPT('mat_.*|dmat_.*')
        FROM events
        WHERE
            team_id = %(team_id)s AND
            $session_id = %(session_id)s AND
            timestamp <= now() AND
            timestamp >= now() - interval 90 day
        LIMIT 400000
        FORMAT JSON
    """
    parameters = {
        "team_id": input.team_id,
        "session_id": input.session_id,
    }

    ch_query_id = str(uuid4())
    logger.info(f"Querying ClickHouse with query_id: {ch_query_id}")

    raw_response: bytes = b""
    async with get_client() as client:
        async with client.aget_query(query=query, query_parameters=parameters, query_id=ch_query_id) as ch_response:
            raw_response = await ch_response.content.read()

    logger.info(f"Received {len(raw_response)} bytes from ClickHouse")

    output_path = Path("/tmp") / str(input.export_id) / "clickhouse" / "events.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("wb") as f:
        f.write(raw_response)

    logger.info(f"Wrote event ClickHouse data to {output_path}")


@activity.defn
async def export_recording_data_prefix(input: ExportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Exporting recording data prefix for session {input.session_id}")

    recording = SessionRecording(session_id=input.session_id, team_id=input.team_id)
    await database_sync_to_async(recording.load_metadata)()
    recording_blocks = await database_sync_to_async(list_blocks)(recording)

    if not recording_blocks:
        logger.warning("No recording blocks found, skipping prefix export")
        return

    first_block = recording_blocks[0]
    _, _, s3_path, _, _, _ = parse.urlparse(first_block.url)
    s3_path = s3_path.lstrip("/")

    prefix = "/".join(s3_path.split("/")[:-1])

    logger.info(f"Found S3 prefix: {prefix}")

    output_path = Path("/tmp") / str(input.export_id) / "s3_prefix.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w") as f:
        f.write(prefix)

    logger.info(f"Wrote S3 prefix to {output_path}")


@activity.defn
async def export_recording_data(input: ExportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Exporting recording data for session {input.session_id}")

    recording = SessionRecording(session_id=input.session_id, team_id=input.team_id)
    await database_sync_to_async(recording.load_metadata)()
    recording_blocks = await database_sync_to_async(list_blocks)(recording)

    logger.info(f"Found {len(recording_blocks)} blocks to export")

    output_files: list[Path] = []

    for block in recording_blocks:
        _, _, s3_path, _, query, _ = parse.urlparse(block.url)

        filename = s3_path.split("/")[-1]

        match = re.match(r"^range=bytes=(\d+)-(\d+)$", query)

        if not match:
            logger.warning(f"Got malformed byte range in block URL: {query}, skipping...")
            continue

        block_offset = int(match.group(1))

        try:
            async with session_recording_v2_object_storage.async_client() as storage:
                block_data = await storage.fetch_block_bytes(block.url)
            logger.info(f"Successfully fetched block data ({len(block_data)} bytes)")
        except session_recording_v2_object_storage.BlockFetchError:
            logger.warning(f"Failed to fetch block at {block.url}, skipping...")
            continue

        output_path = Path("/tmp") / str(input.export_id) / "data" / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("wb") as f:
            f.write(b"\x00" * block_offset)
            f.write(block_data)
            f.write(b"\x00" * 1024)

        logger.info(f"Wrote block data to {output_path}")
        output_files.append(output_path)

    logger.info(f"Exported recording data to {len(output_files)} files")


@activity.defn
async def store_export_data(input: ExportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Storing export data for session {input.session_id}")

    export_dir = Path("/tmp") / str(input.export_id)

    if not export_dir.exists():
        raise RuntimeError(f"Export directory {export_dir} does not exist")

    zip_path = Path("/tmp") / f"{input.export_id}.zip"
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", export_dir)

    logger.info(f"Created zip archive at {zip_path}")

    s3_key = f"session_recording_export/{input.team_id}/{input.session_id}/{input.export_id}.zip"

    async with session_recording_v2_object_storage.async_client() as storage:
        await storage.upload_file(s3_key, str(zip_path))

    logger.info(f"Uploaded zip archive to S3 at {s3_key}")

    zip_path.unlink()

    asset = await ExportedAsset.objects.aget(pk=input.exported_asset_id)
    asset.content_location = s3_key
    await database_sync_to_async(asset.save)(update_fields=["content_location"])

    logger.info(f"Updated ExportedAsset {input.exported_asset_id} with content_location {s3_key}")


@activity.defn
async def cleanup_export_data(input: ExportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Cleaning up export data for session {input.session_id}")

    export_dir = Path("/tmp") / str(input.export_id)
    zip_path = Path("/tmp") / f"{input.export_id}.zip"

    if export_dir.exists():
        shutil.rmtree(export_dir)
        logger.info(f"Deleted export directory {export_dir}")
    else:
        logger.warning(f"Export directory {export_dir} does not exist, skipping cleanup")

    if zip_path.exists():
        zip_path.unlink()
        logger.info(f"Deleted zip file {zip_path}")
