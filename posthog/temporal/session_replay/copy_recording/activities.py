import time
import secrets
from collections.abc import Iterator

from django.conf import settings

import aioboto3
import structlog
from asgiref.sync import sync_to_async
from botocore.client import Config
from temporalio import activity

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team
from posthog.session_recordings.recordings.recording_api_client import recording_api_client
from posthog.session_recordings.session_recording_v2_service import RecordingBlock, fetch_blocks_from_recording_api
from posthog.temporal.session_replay.copy_recording.types import RETENTION_PERIODS, CopySessionInput, CopySessionResult

logger = structlog.get_logger(__name__)

# Keeps each encrypt request under recording-api's 20mb JSON body limit after base64.
MAX_ENCRYPT_BATCH_BYTES = 10 * 1024 * 1024
MAX_ENCRYPT_BATCH_BLOCKS = 100

REPLAY_ROW_EXISTS_QUERY = """
SELECT count() FROM session_replay_events
WHERE team_id = %(team_id)s AND session_id = %(session_id)s
"""

SESSION_EVENT_COUNT_QUERY = """
SELECT count() FROM events
WHERE team_id = %(team_id)s AND `$session_id` = %(session_id)s
  AND timestamp >= parseDateTime64BestEffort(%(start)s, 6, 'UTC') - INTERVAL 1 DAY
  AND timestamp <= parseDateTime64BestEffort(%(end)s, 6, 'UTC') + INTERVAL 1 DAY
"""

# dmat_* columns are per-team slot allocations, so the target team reads these properties from `properties` instead.
COPY_EVENTS_QUERY = """
INSERT INTO writable_events (
    uuid, event, properties, timestamp, team_id, distinct_id, elements_chain, created_at,
    person_id, person_created_at, person_properties,
    group0_properties, group1_properties, group2_properties, group3_properties, group4_properties,
    group0_created_at, group1_created_at, group2_created_at, group3_created_at, group4_created_at,
    person_mode
)
SELECT
    uuid, event, properties, timestamp, %(target_team_id)s, distinct_id, elements_chain, created_at,
    person_id, person_created_at, person_properties,
    group0_properties, group1_properties, group2_properties, group3_properties, group4_properties,
    group0_created_at, group1_created_at, group2_created_at, group3_created_at, group4_created_at,
    person_mode
FROM events
WHERE team_id = %(source_team_id)s AND `$session_id` = %(session_id)s
  AND timestamp >= parseDateTime64BestEffort(%(start)s, 6, 'UTC') - INTERVAL 1 DAY
  AND timestamp <= parseDateTime64BestEffort(%(end)s, 6, 'UTC') + INTERVAL 1 DAY
"""

# AI tags, highlights and surfacing scores are left out so the copy starts unscanned.
COPY_REPLAY_ROW_QUERY = """
INSERT INTO writable_session_replay_events (
    session_id, team_id, distinct_id, min_first_timestamp, max_last_timestamp,
    block_first_timestamps, block_last_timestamps, block_urls,
    first_url, all_urls, click_count, keypress_count, mouse_activity_count, active_milliseconds,
    console_log_count, console_warn_count, console_error_count, size, message_count, event_count,
    snapshot_source, snapshot_library, snapshot_mode_v2, _timestamp, retention_period_days
)
SELECT
    session_id, %(target_team_id)s, any(distinct_id), min(min_first_timestamp), max(max_last_timestamp),
    arrayMap(x -> parseDateTime64BestEffort(x, 6, 'UTC'), %(block_first_timestamps)s),
    arrayMap(x -> parseDateTime64BestEffort(x, 6, 'UTC'), %(block_last_timestamps)s),
    %(block_urls)s,
    argMinMergeState(first_url), groupUniqArrayArray(all_urls), sum(click_count), sum(keypress_count),
    sum(mouse_activity_count), sum(active_milliseconds), sum(console_log_count), sum(console_warn_count),
    sum(console_error_count), sum(size), sum(message_count), sum(event_count),
    argMinMergeState(snapshot_source), argMinMergeState(snapshot_library), argMinMergeState(snapshot_mode_v2),
    now(), %(retention_days)s
FROM session_replay_events
WHERE team_id = %(source_team_id)s AND session_id = %(session_id)s
GROUP BY session_id
HAVING max(is_deleted) = 0
"""


def _batch_blocks(blocks: list[bytes]) -> Iterator[list[bytes]]:
    batch: list[bytes] = []
    batch_bytes = 0
    for block in blocks:
        if batch and (batch_bytes + len(block) > MAX_ENCRYPT_BATCH_BYTES or len(batch) >= MAX_ENCRYPT_BATCH_BLOCKS):
            yield batch
            batch, batch_bytes = [], 0
        batch.append(block)
        batch_bytes += len(block)
    if batch:
        yield batch


def _new_block_key(retention_days: int) -> str:
    # Same shape as the ingestion consumer's batch keys, which recording-api validates before serving a block.
    return f"{settings.SESSION_RECORDING_V2_S3_PREFIX}/{RETENTION_PERIODS[retention_days]}/{int(time.time() * 1000)}-{secrets.token_hex(8)}"


async def _upload(key: str, body: bytes) -> None:
    session = aioboto3.Session()
    async with session.client(  # type: ignore[call-overload]
        "s3",
        endpoint_url=settings.SESSION_RECORDING_V2_S3_ENDPOINT or None,
        aws_access_key_id=settings.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name=settings.SESSION_RECORDING_V2_S3_REGION,
    ) as client:
        await client.put_object(Bucket=settings.SESSION_RECORDING_V2_S3_BUCKET, Key=key, Body=body)


def _count(query: str, params: dict) -> int:
    return int(sync_execute(query, params)[0][0])


def _visible_event_count(team_id: int, session_id: str) -> int:
    team = Team.objects.get(id=team_id)
    response = execute_hogql_query(
        "SELECT count() FROM events WHERE $session_id = {session_id}",
        placeholders={"session_id": ast.Constant(value=session_id)},
        team=team,
    )
    return int(response.results[0][0])


async def _copy_blocks(input: CopySessionInput, source_blocks: list[RecordingBlock]) -> list[str]:
    async with recording_api_client() as client:
        plaintext = [
            await client.fetch_block(b.key, b.start_byte, b.end_byte, input.session_id, input.source_team_id)
            for b in source_blocks
        ]
        encrypted: list[bytes] = []
        for batch in _batch_blocks(plaintext):
            encrypted += await client.encrypt_blocks(
                input.session_id, input.target_team_id, batch, input.retention_days
            )
            activity.heartbeat()

    key = _new_block_key(input.retention_days)
    await _upload(key, b"".join(encrypted))

    urls: list[str] = []
    offset = 0
    for block in encrypted:
        urls.append(
            f"s3://{settings.SESSION_RECORDING_V2_S3_BUCKET}/{key}?range=bytes={offset}-{offset + len(block) - 1}"
        )
        offset += len(block)
    return urls


@activity.defn
async def copy_session_recording(input: CopySessionInput) -> CopySessionResult:
    # The replay row goes in last because a retry treats an existing row as a finished copy.
    tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=input.target_team_id)
    log = logger.bind(session_id=input.session_id, target_team_id=input.target_team_id)
    target = {"team_id": input.target_team_id, "session_id": input.session_id}

    if await sync_to_async(_count)(REPLAY_ROW_EXISTS_QUERY, target):
        log.info("copy_recording.already_copied")
        return CopySessionResult(session_id=input.session_id, status="already_copied")

    source_blocks = await fetch_blocks_from_recording_api(input.session_id, input.source_team_id)
    if not source_blocks:
        log.warning("copy_recording.source_not_found")
        return CopySessionResult(session_id=input.session_id, status="not_found")

    block_urls = await _copy_blocks(input, source_blocks)

    window = {"start": source_blocks[0].start_timestamp, "end": source_blocks[-1].end_timestamp}
    # Events have no unique key, so a retry after this insert must not insert them twice.
    if not await sync_to_async(_count)(SESSION_EVENT_COUNT_QUERY, {**target, **window}):
        await sync_to_async(sync_execute)(
            COPY_EVENTS_QUERY,
            {
                "source_team_id": input.source_team_id,
                "target_team_id": input.target_team_id,
                "session_id": input.session_id,
                **window,
            },
        )
    event_count = await sync_to_async(_count)(SESSION_EVENT_COUNT_QUERY, {**target, **window})

    await sync_to_async(sync_execute)(
        COPY_REPLAY_ROW_QUERY,
        {
            "source_team_id": input.source_team_id,
            "target_team_id": input.target_team_id,
            "session_id": input.session_id,
            "block_first_timestamps": [b.start_timestamp for b in source_blocks],
            "block_last_timestamps": [b.end_timestamp for b in source_blocks],
            "block_urls": block_urls,
            "retention_days": input.retention_days,
        },
    )

    warnings: list[str] = []
    visible = await sync_to_async(_visible_event_count)(input.target_team_id, input.session_id)
    if visible != event_count:
        # HogQL may read the native-JSON events table, which this copy does not write.
        warnings.append(f"HogQL sees {visible} of {event_count} copied events")

    log.info("copy_recording.copied", block_count=len(block_urls), event_count=event_count, warnings=warnings)
    return CopySessionResult(
        session_id=input.session_id,
        status="copied",
        block_count=len(block_urls),
        event_count=event_count,
        warnings=warnings,
    )
