import re
import json
import uuid
import base64
import shutil
from datetime import datetime
from pathlib import Path
from urllib import parse
from uuid import uuid4

from django.conf import settings

import pytz
from temporalio import activity

from posthog.models.exported_recording import ExportedRecording
from posthog.redis import get_async_client
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.session_recording_v2_service import list_blocks
from posthog.storage import session_recording_v2_object_storage
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.export_recording.types import ExportContext, ExportRecordingInput, RedisConfig

LOGGER = get_write_only_logger()


def _redis_url(config: RedisConfig) -> str:
    return config.redis_url or settings.SESSION_RECORDING_REDIS_URL


def _redis_key(export_id: uuid.UUID, key_type: str, suffix: str = "") -> str:
    base_key = f"export-recording:{export_id}:{key_type}"
    return f"{base_key}:{suffix}" if suffix else base_key


@activity.defn
async def build_recording_export_context(input: ExportRecordingInput) -> ExportContext:
    logger = LOGGER.bind()
    logger.info(f"Building export context for recording {input.exported_recording_id}")

    export_record = (
        await ExportedRecording.objects.select_related("team")
        .only("status", "session_id", "team__id")
        .aget(id=input.exported_recording_id)
    )

    export_record.status = ExportedRecording.Status.RUNNING
    await database_sync_to_async(export_record.save)(update_fields=["status"])

    logger.info(f"Built export context for session {export_record.session_id}")

    return ExportContext(
        export_id=uuid.uuid4(),
        exported_recording_id=input.exported_recording_id,
        session_id=export_record.session_id,
        team_id=export_record.team.id,
        redis_config=input.redis_config,
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

    redis_key = _redis_key(input.export_id, "replay-events")
    r = get_async_client(_redis_url(input.redis_config))
    await r.setex(redis_key, input.redis_config.redis_ttl, raw_response)

    logger.info(f"Wrote replay ClickHouse metadata to Redis key {redis_key}")


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

    redis_key = _redis_key(input.export_id, "events")
    r = get_async_client(_redis_url(input.redis_config))
    await r.setex(redis_key, input.redis_config.redis_ttl, raw_response)

    logger.info(f"Wrote event ClickHouse data to Redis key {redis_key}")


@activity.defn
async def export_recording_data_prefix(input: ExportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Exporting recording data prefix for session {input.session_id}")

    recording = SessionRecording(session_id=input.session_id, team_id=input.team_id)
    await database_sync_to_async(recording.load_metadata)()
    recording_blocks = await database_sync_to_async(list_blocks)(recording)

    if not recording_blocks:
        logger.warning("No recording blocks found, skipping prefix export...")
        return

    first_block = recording_blocks[0]
    _, _, s3_path, _, _, _ = parse.urlparse(first_block.url)
    s3_path = s3_path.lstrip("/")

    prefix = "/".join(s3_path.split("/")[:-1])

    logger.info(f"Found S3 prefix: {prefix}")

    redis_key = _redis_key(input.export_id, "s3-prefix")
    r = get_async_client(_redis_url(input.redis_config))
    await r.setex(redis_key, input.redis_config.redis_ttl, prefix)

    logger.info(f"Wrote S3 prefix to Redis key {redis_key}")


@activity.defn
async def export_recording_data(input: ExportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Exporting recording data for session {input.session_id}")

    recording = SessionRecording(session_id=input.session_id, team_id=input.team_id)
    await database_sync_to_async(recording.load_metadata)()
    recording_blocks = await database_sync_to_async(list_blocks)(recording)

    logger.info(f"Found {len(recording_blocks)} blocks to export")

    block_manifest: list[dict] = []

    r = get_async_client(_redis_url(input.redis_config))
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

        redis_key = _redis_key(input.export_id, "block", filename)
        encoded_data = base64.b64encode(block_data).decode("utf-8")
        await r.setex(redis_key, input.redis_config.redis_ttl, encoded_data)

        block_manifest.append(
            {
                "filename": filename,
                "offset": block_offset,
                "redis_key": redis_key,
            }
        )

        logger.info(f"Wrote block data to Redis key {redis_key}")

    manifest_key = _redis_key(input.export_id, "block-manifest")
    await r.setex(manifest_key, input.redis_config.redis_ttl, json.dumps(block_manifest))

    logger.info(f"Exported {len(block_manifest)} recording blocks to Redis")


@activity.defn
async def store_export_data(input: ExportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Storing export data for session {input.session_id}")

    export_dir = Path("/tmp") / str(input.export_id)
    export_dir.mkdir(parents=True, exist_ok=True)

    r = get_async_client(_redis_url(input.redis_config))
    replay_events_data = await r.get(_redis_key(input.export_id, "replay-events"))
    events_data = await r.get(_redis_key(input.export_id, "events"))
    s3_prefix = await r.get(_redis_key(input.export_id, "s3-prefix"))
    block_manifest_raw = await r.get(_redis_key(input.export_id, "block-manifest"))

    clickhouse_dir = export_dir / "clickhouse"
    clickhouse_dir.mkdir(parents=True, exist_ok=True)

    if replay_events_data:
        replay_events_path = clickhouse_dir / "session-replay-events.json"
        with replay_events_path.open("wb") as f:
            f.write(replay_events_data if isinstance(replay_events_data, bytes) else replay_events_data.encode())
        logger.info(f"Wrote replay events to {replay_events_path}")

    if events_data:
        events_path = clickhouse_dir / "events.json"
        with events_path.open("wb") as f:
            f.write(events_data if isinstance(events_data, bytes) else events_data.encode())
        logger.info(f"Wrote events to {events_path}")

    if s3_prefix:
        s3_prefix_path = export_dir / "s3_prefix.txt"
        with s3_prefix_path.open("w") as f:
            f.write(s3_prefix if isinstance(s3_prefix, str) else s3_prefix.decode())
        logger.info(f"Wrote S3 prefix to {s3_prefix_path}")

    if block_manifest_raw:
        data_dir = export_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        block_manifest = json.loads(block_manifest_raw)
        for block_info in block_manifest:
            block_data_encoded = await r.get(block_info["redis_key"])
            if not block_data_encoded:
                logger.warning(f"Missing block data for {block_info['filename']}, skipping...")
                continue

            block_data = base64.b64decode(block_data_encoded)
            block_offset = block_info["offset"]

            output_path = data_dir / block_info["filename"]
            with output_path.open("wb") as f:
                f.write(b"\x00" * block_offset)
                f.write(block_data)
                f.write(b"\x00" * 1024)

            logger.info(f"Wrote block data to {output_path}")

    zip_path = Path("/tmp") / f"{input.export_id}.zip"
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", export_dir)

    logger.info(f"Created zip archive at {zip_path}")

    s3_key = f"session_recording_exports/{input.team_id}/{input.session_id}/{input.export_id}.zip"

    async with session_recording_v2_object_storage.async_client() as storage:
        await storage.upload_file(s3_key, str(zip_path))

    logger.info(f"Uploaded zip archive to S3 at {s3_key}")

    zip_path.unlink()
    shutil.rmtree(export_dir)

    export_record = await ExportedRecording.objects.aget(id=input.exported_recording_id)
    export_record.export_location = s3_key
    export_record.status = ExportedRecording.Status.COMPLETE
    await database_sync_to_async(export_record.save)(update_fields=["export_location", "status"])

    logger.info(f"Updated ExportedRecording {input.exported_recording_id} with export_location {s3_key}")


@activity.defn
async def cleanup_export_data(input: ExportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Cleaning up export data for session {input.session_id}")

    keys_to_delete = [
        _redis_key(input.export_id, "replay-events"),
        _redis_key(input.export_id, "events"),
        _redis_key(input.export_id, "s3-prefix"),
        _redis_key(input.export_id, "block-manifest"),
    ]

    r = get_async_client(_redis_url(input.redis_config))
    block_manifest_raw = await r.get(_redis_key(input.export_id, "block-manifest"))
    if block_manifest_raw:
        block_manifest = json.loads(block_manifest_raw)
        for block_info in block_manifest:
            keys_to_delete.append(block_info["redis_key"])

    if keys_to_delete:
        deleted_count = await r.delete(*keys_to_delete)
        logger.info(f"Deleted {deleted_count} Redis keys for export {input.export_id}")
