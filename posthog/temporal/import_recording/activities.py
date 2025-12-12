import json
import shutil
import zipfile
from pathlib import Path
from uuid import uuid4

from temporalio import activity

from posthog.storage import session_recording_v2_object_storage
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.import_recording.types import ImportContext, ImportRecordingInput

LOGGER = get_write_only_logger()


@activity.defn
async def build_import_context(input: ImportRecordingInput) -> ImportContext:
    logger = LOGGER.bind()
    logger.info(f"Building import context for zip file {input.export_file}")

    zip_path = Path(input.export_file)
    if not zip_path.exists():
        raise RuntimeError(f"Zip file does not exist: {input.export_file}")

    import_id = uuid4()
    import_dir = Path("/tmp") / str(import_id)
    import_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as f_zip:
        f_zip.extractall(import_dir)

    logger.info(f"Extracted zip file to {import_dir}")

    s3_prefix_file = import_dir / "s3_prefix.txt"

    if not s3_prefix_file.exists():
        raise RuntimeError("Missing s3_prefix.txt")

    s3_prefix = s3_prefix_file.read_text().strip()
    logger.info(f"Found S3 prefix: {s3_prefix}")

    replay_events_file = import_dir / "clickhouse" / "session-replay-events.json"
    if not replay_events_file.exists():
        raise RuntimeError("Missing session-replay-events.json")

    with replay_events_file.open("r") as f:
        replay_data = json.load(f)

        if not replay_data.get("data") or len(replay_data["data"]) == 0:
            raise RuntimeError("Missing data in session-replay-events.json")

        first_row = replay_data["data"][0]
        session_id = first_row.get("session_id")
        logger.info(f"Found session_id: {session_id}")

    return ImportContext(team_id=input.team_id, import_id=import_id, s3_prefix=s3_prefix, session_id=session_id)


@activity.defn
async def import_recording_data(input: ImportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Importing recording data for session {input.session_id}")

    data_dir = Path("/tmp") / str(input.import_id) / "data"

    data_files = list(data_dir.iterdir())
    logger.info(f"Found {len(data_files)} data files to import")

    async with session_recording_v2_object_storage.async_client() as storage:
        for data_file in data_files:
            s3_key = f"{input.s3_prefix}/{data_file.name}"
            logger.info(f"Uploading {data_file.name} to {s3_key}")

            await storage.upload_file(s3_key, str(data_file))
            logger.info(f"Successfully uploaded {data_file.name}")

    logger.info(f"Imported {len(data_files)} recording data files")


@activity.defn
async def import_replay_clickhouse_rows(input: ImportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Importing replay ClickHouse rows for session {input.session_id}")

    replay_events_file = Path("/tmp") / str(input.import_id) / "clickhouse" / "session-replay-events.json"
    with replay_events_file.open("r") as f:
        replay_data = json.load(f)

    rows = replay_data.get("data", [])
    if not rows:
        raise RuntimeError("Missing data in session-replay-events.json")

    logger.info(f"Importing {len(rows)} replay event rows")

    query = """
        INSERT INTO writable_session_replay_events (
            session_id,
            team_id,
            distinct_id,
            min_first_timestamp,
            max_last_timestamp,
            first_url,
            click_count,
            keypress_count,
            mouse_activity_count,
            active_milliseconds,
            console_log_count,
            console_warn_count,
            console_error_count,
            snapshot_source,
            snapshot_library,
            retention_period_days,
            block_first_timestamps,
            block_last_timestamps,
            block_urls
        )
        SELECT
            any(session_id),
            any(team_id),
            any(distinct_id),
            any(min_first_timestamp),
            any(max_last_timestamp),
            argMinState(first_url, min_first_timestamp),
            any(click_count),
            any(keypress_count),
            any(mouse_activity_count),
            any(active_milliseconds),
            any(console_log_count),
            any(console_warn_count),
            any(console_error_count),
            argMinState(snapshot_source, min_first_timestamp),
            argMinState(snapshot_library, min_first_timestamp),
            any(retention_period_days),
            any(block_first_timestamps),
            any(block_last_timestamps),
            any(block_urls)
        FROM (
            SELECT
                %(session_id)s as session_id,
                %(team_id)s as team_id,
                %(distinct_id)s as distinct_id,
                CAST(%(min_first_timestamp)s AS DateTime64(6, 'UTC')) as min_first_timestamp,
                CAST(%(max_last_timestamp)s AS DateTime64(6, 'UTC')) as max_last_timestamp,
                CAST(%(first_url)s AS Nullable(String)) as first_url,
                %(click_count)s as click_count,
                %(keypress_count)s as keypress_count,
                %(mouse_activity_count)s as mouse_activity_count,
                %(active_milliseconds)s as active_milliseconds,
                %(console_log_count)s as console_log_count,
                %(console_warn_count)s as console_warn_count,
                %(console_error_count)s as console_error_count,
                CAST(%(snapshot_source)s AS LowCardinality(Nullable(String))) as snapshot_source,
                CAST(NULL AS Nullable(String)) as snapshot_library,
                %(retention_period_days)s as retention_period_days,
                %(block_first_timestamps)s as block_first_timestamps,
                %(block_last_timestamps)s as block_last_timestamps,
                %(block_urls)s as block_urls
        )
    """

    ch_query_id = str(uuid4())
    logger.info(f"Inserting into ClickHouse with query_id: {ch_query_id}")

    try:
        async with get_client() as client:
            for row in rows:
                query_parameters = {
                    "session_id": row["session_id"],
                    "team_id": input.team_id,
                    "distinct_id": row["distinct_id"],
                    "min_first_timestamp": row["start_time"],
                    "max_last_timestamp": row["end_time"],
                    "first_url": row["first_url"],
                    "click_count": row["click_count"],
                    "keypress_count": row["keypress_count"],
                    "mouse_activity_count": row["mouse_activity_count"],
                    "active_milliseconds": row["active_seconds"] * 1000,
                    "console_log_count": row["console_log_count"],
                    "console_warn_count": row["console_warn_count"],
                    "console_error_count": row["console_error_count"],
                    "snapshot_source": row["snapshot_source"],
                    "retention_period_days": row["retention_period_days"],
                    "block_first_timestamps": row["block_first_timestamps"],
                    "block_last_timestamps": row["block_last_timestamps"],
                    "block_urls": row["block_urls"],
                }
                await client.execute_query(query, query_parameters=query_parameters, query_id=ch_query_id)
    except Exception:
        logger.exception("Failed to import replay event rows")
        raise

    logger.info(f"Successfully imported {len(rows)} replay event rows")


@activity.defn
async def import_event_clickhouse_rows(input: ImportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Importing event ClickHouse rows for session {input.session_id}")

    events_file = Path("/tmp") / str(input.import_id) / "clickhouse" / "events.json"
    if not events_file.exists():
        logger.warning("No events.json found, skipping")
        return

    with events_file.open("r") as f:
        events_data = json.load(f)

    rows = events_data.get("data", [])
    if not rows:
        logger.warning("No event rows to import")
        return

    logger.info(f"Importing {len(rows)} event rows")

    query = """
        INSERT INTO writable_events (
            uuid,
            team_id,
            event,
            distinct_id,
            properties,
            timestamp,
            created_at,
            person_id,
            person_properties,
            elements_chain
        ) VALUES
    """

    ch_query_id = str(uuid4())
    logger.info(f"Inserting into ClickHouse with query_id: {ch_query_id}")

    try:
        async with get_client() as client:
            for row in rows:
                data_tuple = (
                    row["uuid"],
                    input.team_id,
                    row["event"],
                    row["distinct_id"],
                    row["properties"],
                    row["timestamp"],
                    row["created_at"],
                    row["person_id"],
                    row["person_properties"],
                    row["elements_chain"],
                )
                await client.execute_query(query, data_tuple, query_id=ch_query_id)
    except Exception:
        logger.exception("Failed to import event rows")
        raise

    logger.info(f"Successfully imported {len(rows)} event rows")


@activity.defn
async def cleanup_import_data(input: ImportContext) -> None:
    logger = LOGGER.bind()
    logger.info(f"Cleaning up import data for session {input.session_id}")

    import_dir = Path("/tmp") / str(input.import_id)

    if import_dir.exists():
        shutil.rmtree(import_dir)
        logger.info(f"Deleted import directory {import_dir}")
    else:
        logger.warning(f"Import directory {import_dir} does not exist, skipping cleanup")
