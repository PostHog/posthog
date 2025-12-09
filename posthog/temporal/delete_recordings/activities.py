import os
import re
import json
from datetime import datetime
from pathlib import Path
from tempfile import mkstemp
from urllib import parse
from uuid import uuid4

from django.conf import settings

import pytz
import redis.asyncio as redis
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.schema import RecordingsQuery

from posthog.models import Team
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.session_recording_v2_service import (
    RecordingBlock,
    RecordingBlockListing,
    build_block_list,
)
from posthog.session_recordings.utils import filter_from_params_to_query
from posthog.storage import session_recording_v2_object_storage
from posthog.storage.session_recording_v2_object_storage import FileDeleteError
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.delete_recordings.metrics import (
    get_block_deleted_counter,
    get_block_deleted_error_counter,
    get_block_loaded_counter,
)
from posthog.temporal.delete_recordings.types import (
    DeleteRecordingError,
    DeleteRecordingMetadataInput,
    GroupRecordingError,
    LoadRecordingError,
    Recording,
    RecordingBlockGroup,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithTeamInput,
    RecordingWithBlocks,
)

LOGGER = get_write_only_logger()


def _parse_block_listing_response(raw_response: bytes) -> list[tuple]:
    if len(raw_response) == 0:
        raise DeleteRecordingError("Got empty response from ClickHouse.")

    try:
        result = json.loads(raw_response)
        first_row = result["data"][0]
        return [
            (
                first_row["start_time"],
                first_row["block_first_timestamps"],
                first_row["block_last_timestamps"],
                first_row["block_urls"],
            )
        ]
    except json.JSONDecodeError as e:
        raise DeleteRecordingError("Unable to parse JSON response from ClickHouse.") from e
    except KeyError as e:
        raise DeleteRecordingError("Got malformed JSON response from ClickHouse.") from e
    except IndexError as e:
        raise DeleteRecordingError("No rows in response from ClickHouse.") from e


@activity.defn(name="load-recording-blocks")
async def load_recording_blocks(input: Recording) -> list[RecordingBlock]:
    bind_contextvars(session_id=input.session_id, team_id=input.team_id)
    logger = LOGGER.bind()
    logger.info("Loading recording blocks")

    query: str = SessionReplayEvents.get_block_listing_query(format="JSON")
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

    block_listing: RecordingBlockListing | None = SessionReplayEvents.build_recording_block_listing(
        input.session_id, _parse_block_listing_response(raw_response)
    )

    logger.info("Building block list")
    blocks: list[RecordingBlock] = build_block_list(input.session_id, input.team_id, block_listing)

    logger.info(f"Successfully loaded {len(blocks)} blocks")
    get_block_loaded_counter().add(len(blocks))
    return blocks


@activity.defn(name="group-recording-blocks")
async def group_recording_blocks(input: RecordingWithBlocks) -> list[RecordingBlockGroup]:
    block_count = len(input.blocks)
    bind_contextvars(session_id=input.recording.session_id, team_id=input.recording.team_id, block_count=block_count)
    logger = LOGGER.bind()
    logger.info("Grouping recording blocks")

    block_map: dict[str, RecordingBlockGroup] = {}

    for block in input.blocks:
        _, _, path, _, query, _ = parse.urlparse(block.url)
        path = path.lstrip("/")

        match = re.match(r"^range=bytes=(\d+)-(\d+)$", query)

        if not match:
            raise GroupRecordingError(f"Got malformed byte range in block URL: {query}")

        start_byte, end_byte = int(match.group(1)), int(match.group(2))

        block_group: RecordingBlockGroup = block_map.get(
            path, RecordingBlockGroup(recording=input.recording, path=path, ranges=[])
        )
        block_group.ranges.append((start_byte, end_byte))
        block_map[path] = block_group

    block_groups: list[RecordingBlockGroup] = list(block_map.values())

    logger.info(f"Grouped {block_count} blocks into {len(block_groups)} groups")
    return block_groups


def overwrite_block(path: str, start_byte: int, block_length: int, buffer_size: int = 1024) -> None:
    with open(path, "rb+") as fp:
        fp.seek(start_byte)

        for _ in range(block_length // buffer_size):
            fp.write(bytearray(buffer_size))

        fp.write(bytearray(block_length % buffer_size))


@activity.defn(name="delete-recording-blocks")
async def delete_recording_blocks(input: RecordingBlockGroup) -> None:
    bind_contextvars(
        session_id=input.recording.session_id, team_id=input.recording.team_id, block_count=len(input.ranges)
    )
    logger = LOGGER.bind()
    logger.info("Deleting recording blocks")

    async with session_recording_v2_object_storage.async_client() as storage:
        block_deleted_counter = 0
        block_deleted_error_counter = 0

        tmpfile_path = None
        tmpfile_fd = None
        try:
            tmpfile_fd, tmpfile_path = mkstemp()

            await storage.download_file(input.path, tmpfile_path)

            for start_byte, end_byte in input.ranges:
                try:
                    block_length = end_byte - start_byte + 1

                    size_before = Path(tmpfile_path).stat().st_size

                    overwrite_block(tmpfile_path, start_byte, block_length)

                    size_after = Path(tmpfile_path).stat().st_size

                    assert size_before == size_after
                    block_deleted_counter += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to delete block at range ({start_byte}, {end_byte}) in file at {input.path}, skipping..."
                    )
                    logger.warning(f"Got exception {e}")
                    block_deleted_error_counter += 1

            await storage.upload_file(input.path, tmpfile_path)

            logger.info(f"Deleted {len(input.ranges)} blocks in {input.path}")
        except session_recording_v2_object_storage.FileDownloadError:
            logger.warning(f"Failed to download file at {input.path}, skipping...")
        except session_recording_v2_object_storage.FileUploadError:
            logger.warning(f"Failed to upload file to {input.path}, skipping...")
        finally:
            if tmpfile_fd is not None:
                try:
                    os.close(tmpfile_fd)
                except OSError:
                    pass

            if tmpfile_path is not None:
                try:
                    os.remove(tmpfile_path)
                except FileNotFoundError:
                    pass

    get_block_deleted_counter().add(block_deleted_counter)
    get_block_deleted_error_counter().add(block_deleted_error_counter)
    logger.info(f"Successfully deleted {block_deleted_counter} blocks")
    logger.info(f"Skipped {block_deleted_error_counter} blocks")


def _parse_session_recording_list_response(raw_response: bytes) -> list[str]:
    if len(raw_response) == 0:
        raise LoadRecordingError("Got empty response from ClickHouse.")

    try:
        result = json.loads(raw_response)
        rows = result["data"]
        return [session["session_id"] for session in rows]
    except json.JSONDecodeError as e:
        raise LoadRecordingError("Unable to parse JSON response from ClickHouse.") from e
    except KeyError as e:
        raise LoadRecordingError("Got malformed JSON response from ClickHouse.") from e


@activity.defn(name="load-recordings-with-person")
async def load_recordings_with_person(input: RecordingsWithPersonInput) -> list[str]:
    bind_contextvars(distinct_ids=input.distinct_ids, team_id=input.team_id)
    logger = LOGGER.bind()
    logger.info(f"Loading all sessions for {len(input.distinct_ids)} distinct IDs")

    query: str = SessionReplayEvents.get_sessions_from_distinct_id_query(format="JSON")
    parameters = {
        "team_id": input.team_id,
        "distinct_ids": input.distinct_ids,
        "python_now": datetime.now(pytz.timezone("UTC")),
    }

    ch_query_id = str(uuid4())
    logger.info(f"Querying ClickHouse with query_id: {ch_query_id}")
    raw_response: bytes = b""
    async with get_client() as client:
        async with client.aget_query(query=query, query_parameters=parameters, query_id=ch_query_id) as ch_response:
            raw_response = await ch_response.content.read()

    session_ids: list[str] = _parse_session_recording_list_response(raw_response)
    logger.info(f"Successfully loaded {len(session_ids)} session IDs")
    return session_ids


@activity.defn(name="load-recordings-with-team-id")
async def load_recordings_with_team_id(input: RecordingsWithTeamInput) -> list[str]:
    bind_contextvars(team_id=input.team_id)
    logger = LOGGER.bind()
    logger.info(f"Loading all sessions for team ID {input.team_id}")

    query: str = SessionReplayEvents.get_sessions_from_team_id_query(format="JSON")
    parameters = {
        "team_id": input.team_id,
        "python_now": datetime.now(pytz.timezone("UTC")),
    }

    ch_query_id = str(uuid4())
    logger.info(f"Querying ClickHouse with query_id: {ch_query_id}")
    raw_response: bytes = b""
    async with get_client() as client:
        async with client.aget_query(query=query, query_parameters=parameters, query_id=ch_query_id) as ch_response:
            raw_response = await ch_response.content.read()

    session_ids: list[str] = _parse_session_recording_list_response(raw_response)
    logger.info(f"Successfully loaded {len(session_ids)} session IDs")
    return session_ids


METADATA_DELETION_KEY = "metadata-deletion-queue"


@activity.defn(name="schedule-recording-metadata-deletion")
async def schedule_recording_metadata_deletion(input: Recording) -> None:
    bind_contextvars(session_id=input.session_id, team_id=input.team_id)
    logger = LOGGER.bind()
    logger.info("Scheduling recording metadata deletion")

    async with redis.from_url(settings.SESSION_RECORDING_REDIS_URL) as r:
        await r.sadd(METADATA_DELETION_KEY, input.session_id)

    logger.info("Scheduled recording metadata deletion")


@activity.defn(name="delete-recording-lts-data")
async def delete_recording_lts_data(input: Recording) -> None:
    bind_contextvars(session_id=input.session_id, team_id=input.team_id)
    logger = LOGGER.bind()
    logger.info("Deleting recording LTS data")

    recording = await SessionRecording.objects.filter(session_id=input.session_id, team_id=input.team_id).afirst()

    if recording is None:
        logger.info("Recording not found in Postgres, skipping LTS deletion...")
        return

    if not recording.full_recording_v2_path:
        logger.info("Recording has no LTS path, skipping LTS deletion...")
        return

    logger.info(f"Deleting LTS file at path: {recording.full_recording_v2_path}")

    try:
        async with session_recording_v2_object_storage.async_client() as storage:
            await storage.delete_file(recording.full_recording_v2_path)
        logger.info("Successfully deleted LTS file")
    except FileDeleteError:
        logger.warning(f"Failed to delete LTS file at {recording.full_recording_v2_path}, skipping...")


@activity.defn(name="perform-recording-metadata-deletion")
async def perform_recording_metadata_deletion(input: DeleteRecordingMetadataInput) -> None:
    logger = LOGGER.bind()
    logger.info("Performing recording metadata deletion")

    async with redis.from_url(settings.SESSION_RECORDING_REDIS_URL) as r:
        session_ids: set[bytes] = await r.smembers(METADATA_DELETION_KEY)

    if not session_ids:
        logger.info("No session IDs to delete")
        return

    session_id_list = [sid.decode("utf-8") for sid in session_ids]
    logger.info(f"Found {len(session_id_list)} session IDs to delete")

    # Delete from ClickHouse
    query = """
        ALTER TABLE session_replay_events
        DELETE WHERE session_id IN %(session_ids)s
    """

    if input.dry_run:
        logger.info("DRY RUN: Skipping ClickHouse DELETE")
    else:
        ch_query_id = str(uuid4())
        logger.info(f"Executing ClickHouse DELETE with query_id: {ch_query_id}")

        async with get_client() as client:
            await client.execute_query(
                query,
                query_parameters={"session_ids": session_id_list},
                query_id=ch_query_id,
            )

    if input.dry_run:
        postgres_to_delete_count = await SessionRecording.objects.filter(session_id__in=session_id_list).acount()
        logger.info(f"DRY RUN: Would delete {postgres_to_delete_count} SessionRecording rows from Postgres")

        viewed_to_delete_count = await SessionRecordingViewed.objects.filter(session_id__in=session_id_list).acount()
        logger.info(f"DRY RUN: Would delete {viewed_to_delete_count} SessionRecordingViewed rows from Postgres")
    else:
        # Delete from Postgres (SessionRecordingPlaylistItem is cascade deleted via FK)
        postgres_deleted_count, _ = await SessionRecording.objects.filter(session_id__in=session_id_list).adelete()
        logger.info(f"Deleted {postgres_deleted_count} SessionRecording rows from Postgres")

        viewed_deleted_count, _ = await SessionRecordingViewed.objects.filter(session_id__in=session_id_list).adelete()
        logger.info(f"Deleted {viewed_deleted_count} SessionRecordingViewed rows from Postgres")

        async with redis.from_url(settings.SESSION_RECORDING_REDIS_URL) as r:
            await r.srem(METADATA_DELETION_KEY, *session_ids)

    logger.info(f"Successfully deleted metadata for {len(session_id_list)} sessions")


@activity.defn(name="load-recordings-with-query")
async def load_recordings_with_query(input: RecordingsWithQueryInput) -> list[str]:
    logger = LOGGER.bind()
    logger.info(f"Loading all sessions matching query")

    query_dict = dict(parse.parse_qsl(input.query))
    query_dict.pop("add_events_to_property_queries", None)
    parsed_query = filter_from_params_to_query(query_dict)
    parsed_query.limit = input.query_limit

    team = (
        await Team.objects.select_related("organization")
        .only("id", "organization__available_product_features")
        .aget(id=input.team_id)
    )

    session_ids = []

    async def get_session_ids(query: RecordingsQuery, batch_count: int) -> tuple[bool, str | None]:
        query_instance = SessionRecordingListFromQuery(
            query=query,
            team=team,
            hogql_query_modifiers=None,
        )
        query_results = await database_sync_to_async(query_instance.run)()
        new_sessions = [session["session_id"] for session in query_results.results]
        session_ids.extend(new_sessions)

        logger.info(f"Loaded recording batch {batch_count}", session_count=len(new_sessions))

        return query_results.has_more_recording, query_results.next_cursor

    batch_count = 1
    has_more_recording, next_cursor = await get_session_ids(parsed_query, batch_count)
    while has_more_recording:
        if next_cursor is None:
            break

        batch_count += 1
        parsed_query.after = next_cursor
        has_more_recording, next_cursor = await get_session_ids(parsed_query, batch_count)

    logger.info(f"Finished loading sessions to be deleted", session_count=len(session_ids))
    return session_ids
