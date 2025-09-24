import json
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import pytz
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.session_recordings.session_recording_api import SessionReplayEvents
from posthog.session_recordings.session_recording_v2_service import RecordingBlock, build_block_list
from posthog.storage import session_recording_v2_object_storage
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater


class DeleteRecordingError(Exception):
    pass


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
        raise DeleteRecordingError("Unable to parse JSON response from ClickHouse") from e
    except KeyError as e:
        raise DeleteRecordingError("Got malformed JSON response from ClickHouse.") from e


@dataclass(frozen=True)
class LoadRecordingBlocksInput:
    session_id: str
    team_id: int


@activity.defn(name="load_recording_blocks")
async def load_recording_blocks(input: LoadRecordingBlocksInput) -> list[RecordingBlock]:
    async with Heartbeater():
        query: str = SessionReplayEvents.get_block_listing_query(format="JSON")
        parameters = {
            "team_id": input.team_id,
            "session_id": input.session_id,
            "python_now": datetime.now(pytz.timezone("UTC")),
            "ttl_days": 365,
        }

        raw_response: bytes = b""
        async with get_client() as client:
            async with client.aget_query(
                query=query, query_parameters=parameters, query_id=str(uuid4())
            ) as ch_response:
                raw_response = await ch_response.content.read()

        block_listing = SessionReplayEvents.build_recording_block_listing(
            input.session_id, _parse_block_listing_response(raw_response)
        )
        return build_block_list(input.session_id, input.team_id, block_listing)


@dataclass(frozen=True)
class DeleteRecordingBlocksInput:
    blocks: list[RecordingBlock]


@activity.defn(name="delete_recording_block")
async def delete_recording_blocks(input: DeleteRecordingBlocksInput) -> None:
    async with Heartbeater():
        storage = session_recording_v2_object_storage.client()
        for block in input.blocks:
            await sync_to_async(storage.delete_block)(block.url)
