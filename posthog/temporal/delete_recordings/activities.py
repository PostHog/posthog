import os
import re
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from tempfile import mkstemp
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import pytz
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.session_recording_v2_service import (
    RecordingBlock,
    RecordingBlockListing,
    build_block_list,
)
from posthog.storage import session_recording_v2_object_storage
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.delete_recordings.metrics import (
    get_block_deleted_counter,
    get_block_deleted_error_counter,
    get_block_loaded_counter,
)
from posthog.temporal.delete_recordings.types import (
    DeleteRecordingError,
    LoadRecordingError,
    Recording,
    RecordingsWithPersonInput,
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
        "ttl_days": 365,
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
async def group_recording_blocks(input: RecordingWithBlocks) -> list[list[RecordingBlock]]:
    block_count = len(input.blocks)
    bind_contextvars(session_id=input.recording.session_id, team_id=input.recording.team_id, block_count=block_count)
    logger = LOGGER.bind()
    logger.info("Grouping recording blocks")

    block_map = defaultdict(list)

    for block in input.blocks:
        scheme, netloc, path, _, _, _ = urlparse(block.url)
        base_key = urlunparse((scheme, netloc, path, None, None, None))
        block_map[base_key].append(block)

    block_groups: list[list[RecordingBlock]] = list(block_map.values())

    logger.info(f"Grouped {block_count} blocks into {len(block_groups)} groups")
    return block_groups


def overwrite_block(path: str, start_byte: int, block_length: int, buffer_size: int = 1024) -> None:
    with open(path, "rb+") as fp:
        fp.seek(start_byte)

        for _ in range(block_length // buffer_size):
            fp.write(bytearray(buffer_size))

        fp.write(bytearray(block_length % buffer_size))


@activity.defn(name="delete-recording-blocks")
async def delete_recording_blocks(input: RecordingWithBlocks) -> None:
    bind_contextvars(
        session_id=input.recording.session_id, team_id=input.recording.team_id, block_count=len(input.blocks)
    )
    logger = LOGGER.bind()
    logger.info("Deleting recording blocks")

    async with session_recording_v2_object_storage.async_client() as storage:
        block_deleted_counter = 0
        block_deleted_error_counter = 0

        for block in input.blocks:
            _, _, path, _, query, _ = urlparse(block.url)
            match = re.match(r"^range=bytes=(\d+)-(\d+)$", query)

            if not match:
                raise DeleteRecordingError(f"Got malformed byte range in block URL: {query}")

            start_byte, end_byte = int(match.group(1)), int(match.group(2))
            block_length = end_byte - start_byte + 1
            key = path.lstrip("/")

            tmpfile = None
            try:
                _, tmpfile = mkstemp()

                await storage.download_file(key, tmpfile)

                size_before = Path(tmpfile).stat().st_size

                overwrite_block(tmpfile, start_byte, block_length)

                size_after = Path(tmpfile).stat().st_size

                assert size_before == size_after

                await storage.upload_file(key, tmpfile)

                logger.info(f"Deleted block at {block.url}")
                block_deleted_counter += 1
            except session_recording_v2_object_storage.FileDownloadError:
                logger.warning(f"Failed to download block at {block.url}, skipping...")
                block_deleted_error_counter += 1
            except session_recording_v2_object_storage.FileUploadError:
                logger.warning(f"Failed to upload block at {block.url}, skipping...")
                block_deleted_error_counter += 1
            finally:
                if tmpfile is not None:
                    os.remove(tmpfile)

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
        "ttl_days": 365,
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
