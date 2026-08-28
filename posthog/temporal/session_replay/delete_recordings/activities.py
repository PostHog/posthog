import json
from datetime import UTC, datetime
from urllib import parse
from uuid import uuid4

from django.conf import settings

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team
from posthog.security.outbound_proxy import internal_httpx_async_client
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.recordings.recording_api_jwt import recording_api_auth_headers
from posthog.session_recordings.utils import filter_from_params_to_query
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.session_replay.delete_recordings import object_storage as chunk_storage
from posthog.temporal.session_replay.delete_recordings.types import (
    CleanupChunksInput,
    DeleteRecordingsInput,
    DeleteRecordingsResult,
    DeleteTeamMetadataInput,
    LoadChunkInput,
    LoadRecordingError,
    LoadRecordingsPage,
    PurgeDeletedMetadataInput,
    PurgeDeletedMetadataResult,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithTeamInput,
)

LOGGER = get_write_only_logger()

# Bounds one purge run. Markers past the cap wait for the next nightly run.
PURGE_MARKER_LIMIT = 100_000
# Bounds one DELETE statement, to keep the query under the ClickHouse query-size limit.
PURGE_DELETE_BATCH_SIZE = 1_000


def purge_select_markers_query() -> str:
    """Find the (team_id, session_id) pairs whose deletion marker is past the grace period.

    Reads the distributed table: the marker is written with an empty distinct_id, and the
    Distributed engine shards on sipHash64(distinct_id), so the marker usually lands on a
    different shard than the recording's other rows. A shard-local subquery would miss it.
    """
    return """
        SELECT DISTINCT team_id, session_id
        FROM session_replay_events
        WHERE is_deleted = 1
          AND _timestamp < now() - INTERVAL %(grace_period_days)s DAY
        LIMIT %(limit)s
    """


def purge_delete_sessions_query() -> str:
    """Delete every stored row of the marked sessions, in one team's batch.

    The marker carries min_first_timestamp = deletion time, so it sits in a different
    partition and sort-key range than the recording's real rows and never merges with
    them. Deleting by (team_id, session_id) removes the recording's rows and the marker;
    a `WHERE is_deleted = 1` predicate would only ever match the marker.
    """
    return f"""
        DELETE FROM sharded_session_replay_events
        ON CLUSTER '{CLICKHOUSE_CLUSTER}'
        WHERE team_id = %(team_id)s AND session_id IN %(session_ids)s
    """


def delete_team_metadata_query() -> str:
    """Delete all replay metadata for a team. The table has no TTL, so nothing else removes it."""
    return f"""
        DELETE FROM sharded_session_replay_events
        ON CLUSTER '{CLICKHOUSE_CLUSTER}'
        WHERE team_id = %(team_id)s
    """


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
async def load_recordings_with_person(input: RecordingsWithPersonInput) -> LoadRecordingsPage:
    bind_contextvars(distinct_ids=input.distinct_ids, team_id=input.team_id)
    tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=input.team_id)
    logger = LOGGER.bind()
    logger.info("Loading sessions for distinct IDs", distinct_id_count=len(input.distinct_ids), cursor=input.cursor)

    query: str = SessionReplayEvents.get_sessions_from_distinct_id_query(format="JSON", paginated=True)
    parameters: dict = {
        "team_id": input.team_id,
        "distinct_ids": input.distinct_ids,
        "python_now": datetime.now(UTC),
        "cursor": input.cursor or "",
        "page_size": input.page_size,
    }

    ch_query_id = str(uuid4())
    logger.info("Querying ClickHouse", query_id=ch_query_id)
    raw_response: bytes = b""
    async with get_client() as client:
        async with client.aget_query(query=query, query_parameters=parameters, query_id=ch_query_id) as ch_response:
            raw_response = await ch_response.content.read()

    session_ids: list[str] = _parse_session_recording_list_response(raw_response)
    next_cursor = session_ids[-1] if len(session_ids) == input.page_size else None
    logger.info("Loaded session IDs page", session_count=len(session_ids), has_more=next_cursor is not None)
    return LoadRecordingsPage(session_ids=session_ids, next_cursor=next_cursor)


@activity.defn(name="load-recordings-with-team-id")
async def load_recordings_with_team_id(input: RecordingsWithTeamInput) -> LoadRecordingsPage:
    bind_contextvars(team_id=input.team_id)
    tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=input.team_id)
    logger = LOGGER.bind()
    logger.info("Loading sessions for team", cursor=input.cursor)

    query: str = SessionReplayEvents.get_sessions_from_team_id_query(format="JSON", paginated=True)
    parameters: dict = {
        "team_id": input.team_id,
        "python_now": datetime.now(UTC),
        "cursor": input.cursor or "",
        "page_size": input.page_size,
    }

    ch_query_id = str(uuid4())
    logger.info("Querying ClickHouse", query_id=ch_query_id)
    raw_response: bytes = b""
    async with get_client() as client:
        async with client.aget_query(query=query, query_parameters=parameters, query_id=ch_query_id) as ch_response:
            raw_response = await ch_response.content.read()

    session_ids: list[str] = _parse_session_recording_list_response(raw_response)
    next_cursor = session_ids[-1] if len(session_ids) == input.page_size else None
    logger.info("Loaded session IDs page", session_count=len(session_ids), has_more=next_cursor is not None)
    return LoadRecordingsPage(session_ids=session_ids, next_cursor=next_cursor)


@activity.defn(name="load-recordings-with-query")
async def load_recordings_with_query(input: RecordingsWithQueryInput) -> LoadRecordingsPage:
    bind_contextvars(team_id=input.team_id)
    tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=input.team_id)
    logger = LOGGER.bind()
    logger.info("Loading sessions matching query", cursor=input.cursor)

    query_dict = dict(parse.parse_qsl(input.query))
    query_dict.pop("add_events_to_property_queries", None)
    parsed_query = filter_from_params_to_query(query_dict)
    parsed_query.limit = input.query_limit

    if input.cursor:
        parsed_query.after = input.cursor

    team = (
        await Team.objects.select_related("organization")
        .only("id", "organization__available_product_features")
        .aget(id=input.team_id)
    )

    query_instance = SessionRecordingListFromQuery(
        query=parsed_query,
        team=team,
        hogql_query_modifiers=None,
    )
    query_results = await database_sync_to_async(query_instance.run)()
    session_ids = [session["session_id"] for session in query_results.results]
    next_cursor = query_results.next_cursor if query_results.has_more_recording else None

    logger.info("Loaded session IDs page", session_count=len(session_ids), has_more=next_cursor is not None)
    return LoadRecordingsPage(session_ids=session_ids, next_cursor=next_cursor)


def _parse_marker_pairs(raw_response: bytes) -> list[tuple[int, str]]:
    if len(raw_response) == 0:
        raise LoadRecordingError("Got empty response from ClickHouse.")

    try:
        rows = json.loads(raw_response)["data"]
        return [(int(row["team_id"]), row["session_id"]) for row in rows]
    except json.JSONDecodeError as e:
        raise LoadRecordingError("Unable to parse JSON response from ClickHouse.") from e
    except KeyError as e:
        raise LoadRecordingError("Got malformed JSON response from ClickHouse.") from e


@activity.defn(name="purge-deleted-metadata")
async def purge_deleted_metadata(input: PurgeDeletedMetadataInput) -> PurgeDeletedMetadataResult:
    """Purge metadata from ClickHouse for recordings that have been deleted.

    This runs nightly. It finds sessions whose deletion marker is older than the grace
    period, then deletes every stored row of those sessions by (team_id, session_id).
    The grace period provides a safety buffer for recovery if needed.
    """
    started_at = datetime.now(UTC)
    logger = LOGGER.bind()
    logger.info(
        "Starting metadata purge for deleted recordings",
        grace_period_days=input.grace_period_days,
    )

    if not (1 <= input.grace_period_days <= 365):
        raise ValueError(f"grace_period_days must be between 1 and 365, got {input.grace_period_days}")

    select_query = purge_select_markers_query() + " FORMAT JSON"
    select_parameters = {"grace_period_days": input.grace_period_days, "limit": PURGE_MARKER_LIMIT}

    async with get_client() as client:
        raw_response: bytes = b""
        async with client.aget_query(
            query=select_query, query_parameters=select_parameters, query_id=str(uuid4())
        ) as ch_response:
            raw_response = await ch_response.content.read()

        pairs = _parse_marker_pairs(raw_response)
        if len(pairs) >= PURGE_MARKER_LIMIT:
            logger.warning("Marker limit reached; remaining markers wait for the next run", limit=PURGE_MARKER_LIMIT)

        sessions_by_team: dict[int, list[str]] = {}
        for team_id, session_id in pairs:
            sessions_by_team.setdefault(team_id, []).append(session_id)

        for team_id, session_ids in sessions_by_team.items():
            for start in range(0, len(session_ids), PURGE_DELETE_BATCH_SIZE):
                batch = session_ids[start : start + PURGE_DELETE_BATCH_SIZE]
                await client.execute_query(
                    purge_delete_sessions_query(),
                    query_id=str(uuid4()),
                    query_parameters={"team_id": team_id, "session_ids": batch},
                )

    completed_at = datetime.now(UTC)
    logger.info(
        "Metadata purge completed",
        session_count=len(pairs),
        team_count=len(sessions_by_team),
        duration_seconds=(completed_at - started_at).total_seconds(),
    )

    return PurgeDeletedMetadataResult(
        started_at=started_at,
        completed_at=completed_at,
    )


@activity.defn(name="delete-team-metadata")
async def delete_team_metadata(input: DeleteTeamMetadataInput) -> None:
    """Delete all ClickHouse replay metadata for a team, after its recordings are shredded."""
    bind_contextvars(team_id=input.team_id)
    logger = LOGGER.bind()
    logger.info("Deleting all replay metadata for team")

    async with get_client() as client:
        await client.execute_query(
            delete_team_metadata_query(),
            query_id=str(uuid4()),
            query_parameters={"team_id": input.team_id},
        )

    logger.info("Replay metadata deleted for team")


@activity.defn(name="delete-recordings")
async def delete_recordings(input: DeleteRecordingsInput) -> DeleteRecordingsResult:
    """Delete recordings via the recording API."""
    bind_contextvars(team_id=input.team_id, session_count=len(input.session_ids), dry_run=input.dry_run)
    logger = LOGGER.bind()

    if input.dry_run:
        logger.info("Dry run: skipping deletion")
        return DeleteRecordingsResult(deleted=[])

    logger.info("Deleting recordings via recording API")

    recording_api_url = settings.RECORDING_API_URL
    if not recording_api_url:
        raise RuntimeError("RECORDING_API_URL is not configured")

    url = f"{recording_api_url}/api/projects/{input.team_id}/recordings/delete"

    headers = recording_api_auth_headers(input.team_id, "delete")

    async with internal_httpx_async_client(timeout=60.0, headers=headers) as client:
        response = await client.post(url, json={"session_ids": input.session_ids, "deleted_by": input.deleted_by})
        response.raise_for_status()
        data = response.json()

    deleted = [r["sessionId"] for r in data if r.get("ok")]
    failed_count = len(data) - len(deleted)

    logger.info(
        "Delete batch completed",
        deleted_count=len(deleted),
        failed_count=failed_count,
    )

    return DeleteRecordingsResult(deleted=deleted, failed_count=failed_count)


@activity.defn(name="load-session-id-chunk")
async def load_session_id_chunk(input: LoadChunkInput) -> LoadRecordingsPage:
    logger = LOGGER.bind()
    logger.info("Loading session ID chunk from S3", chunk_index=input.chunk_index, s3_prefix=input.s3_prefix)

    session_ids = await chunk_storage.load_session_id_chunk(input.s3_prefix, input.chunk_index)

    logger.info("Loaded session ID chunk", session_count=len(session_ids))
    return LoadRecordingsPage(session_ids=session_ids)


@activity.defn(name="cleanup-session-id-chunks")
async def cleanup_session_id_chunks(input: CleanupChunksInput) -> None:
    logger = LOGGER.bind()
    logger.info("Cleaning up session ID chunks from S3", s3_prefix=input.s3_prefix, total_chunks=input.total_chunks)

    try:
        await chunk_storage.delete_session_id_chunks(input.s3_prefix, input.total_chunks)
        logger.info("Cleanup completed")
    except Exception as e:
        logger.warning("Cleanup failed", error=str(e))
