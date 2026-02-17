import json
from datetime import UTC, datetime
from urllib import parse
from uuid import uuid4

from django.conf import settings

import httpx
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.schema import RecordingsQuery

from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.models import Team
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.utils import filter_from_params_to_query
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.delete_recordings.types import (
    BulkDeleteInput,
    BulkDeleteResult,
    DeleteFailure,
    LoadRecordingError,
    PurgeDeletedMetadataInput,
    PurgeDeletedMetadataResult,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithTeamInput,
)

LOGGER = get_write_only_logger()


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
    tag_queries(product=Product.REPLAY, team_id=input.team_id)
    logger = LOGGER.bind()
    logger.info("Loading all sessions for distinct IDs", distinct_id_count=len(input.distinct_ids))

    query: str = SessionReplayEvents.get_sessions_from_distinct_id_query(format="JSON")
    parameters = {
        "team_id": input.team_id,
        "distinct_ids": input.distinct_ids,
        "python_now": datetime.now(UTC),
    }

    ch_query_id = str(uuid4())
    logger.info("Querying ClickHouse", query_id=ch_query_id)
    raw_response: bytes = b""
    async with get_client() as client:
        async with client.aget_query(query=query, query_parameters=parameters, query_id=ch_query_id) as ch_response:
            raw_response = await ch_response.content.read()

    session_ids: list[str] = _parse_session_recording_list_response(raw_response)
    logger.info("Successfully loaded session IDs", session_count=len(session_ids))
    return session_ids


@activity.defn(name="load-recordings-with-team-id")
async def load_recordings_with_team_id(input: RecordingsWithTeamInput) -> list[str]:
    bind_contextvars(team_id=input.team_id)
    tag_queries(product=Product.REPLAY, team_id=input.team_id)
    logger = LOGGER.bind()
    logger.info("Loading all sessions for team")

    query: str = SessionReplayEvents.get_sessions_from_team_id_query(format="JSON")
    parameters = {
        "team_id": input.team_id,
        "python_now": datetime.now(UTC),
    }

    ch_query_id = str(uuid4())
    logger.info("Querying ClickHouse", query_id=ch_query_id)
    raw_response: bytes = b""
    async with get_client() as client:
        async with client.aget_query(query=query, query_parameters=parameters, query_id=ch_query_id) as ch_response:
            raw_response = await ch_response.content.read()

    session_ids: list[str] = _parse_session_recording_list_response(raw_response)
    logger.info("Successfully loaded session IDs", session_count=len(session_ids))
    return session_ids


@activity.defn(name="load-recordings-with-query")
async def load_recordings_with_query(input: RecordingsWithQueryInput) -> list[str]:
    bind_contextvars(team_id=input.team_id)
    tag_queries(product=Product.REPLAY, team_id=input.team_id)
    logger = LOGGER.bind()
    logger.info("Loading all sessions matching query")

    query_dict = dict(parse.parse_qsl(input.query))
    query_dict.pop("add_events_to_property_queries", None)
    parsed_query = filter_from_params_to_query(query_dict)
    parsed_query.limit = input.query_limit

    team = (
        await Team.objects.select_related("organization")
        .only("id", "organization__available_product_features")
        .aget(id=input.team_id)
    )

    session_ids: list[str] = []

    async def get_session_ids(query: RecordingsQuery, batch_count: int) -> tuple[bool, str | None]:
        query_instance = SessionRecordingListFromQuery(
            query=query,
            team=team,
            hogql_query_modifiers=None,
        )
        query_results = await database_sync_to_async(query_instance.run)()
        new_sessions = [session["session_id"] for session in query_results.results]
        session_ids.extend(new_sessions)

        logger.info("Loaded recording batch", batch=batch_count, session_count=len(new_sessions))

        return query_results.has_more_recording, query_results.next_cursor

    batch_count = 1
    has_more_recording, next_cursor = await get_session_ids(parsed_query, batch_count)
    while has_more_recording:
        if next_cursor is None:
            break

        batch_count += 1
        parsed_query.after = next_cursor
        has_more_recording, next_cursor = await get_session_ids(parsed_query, batch_count)

    logger.info("Finished loading sessions to be deleted", session_count=len(session_ids))
    return session_ids


@activity.defn(name="purge-deleted-metadata")
async def purge_deleted_metadata(input: PurgeDeletedMetadataInput) -> PurgeDeletedMetadataResult:
    """Purge metadata from ClickHouse for recordings that have been deleted.

    This runs nightly to clean up metadata.
    Uses lightweight DELETE to remove rows where is_deleted=1 and older than the grace period.
    The grace period provides a safety buffer for recovery if needed.
    """
    from posthog.settings.data_stores import CLICKHOUSE_CLUSTER

    started_at = datetime.now(UTC)
    logger = LOGGER.bind()
    logger.info(
        "Starting metadata purge for deleted recordings",
        grace_period_days=input.grace_period_days,
    )

    query_id = str(uuid4())

    if not (1 <= input.grace_period_days <= 365):
        raise ValueError(f"grace_period_days must be between 1 and 365, got {input.grace_period_days}")

    delete_query = f"""
        DELETE FROM sharded_session_replay_events
        ON CLUSTER '{CLICKHOUSE_CLUSTER}'
        WHERE is_deleted = 1
          AND _timestamp < now() - INTERVAL {{grace_period_days:Int32}} DAY
    """

    logger.info("Executing delete query", query_id=query_id)
    async with get_client() as client:
        await client.execute_query(
            delete_query,
            query_id=query_id,
            query_parameters={"grace_period_days": input.grace_period_days},
        )

    completed_at = datetime.now(UTC)
    logger.info(
        "Metadata purge completed",
        duration_seconds=(completed_at - started_at).total_seconds(),
    )

    return PurgeDeletedMetadataResult(
        started_at=started_at,
        completed_at=completed_at,
    )


@activity.defn(name="bulk-delete-recordings")
async def bulk_delete_recordings(input: BulkDeleteInput) -> BulkDeleteResult:
    """Bulk delete recordings via the recording API bulk-delete endpoint."""
    bind_contextvars(team_id=input.team_id, session_count=len(input.session_ids), dry_run=input.dry_run)
    logger = LOGGER.bind()

    if input.dry_run:
        logger.info("Dry run: skipping deletion")
        return BulkDeleteResult(deleted=[], failed=[])

    logger.info("Deleting recordings via recording API")

    recording_api_url = settings.RECORDING_API_URL
    if not recording_api_url:
        raise RuntimeError("RECORDING_API_URL is not configured")

    url = f"{recording_api_url}/api/projects/{input.team_id}/recordings/bulk_delete"

    headers: dict[str, str] = {}
    if settings.INTERNAL_API_SECRET:
        headers["X-Internal-Api-Secret"] = settings.INTERNAL_API_SECRET

    async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
        response = await client.post(url, json={"session_ids": input.session_ids})
        response.raise_for_status()
        data = response.json()

    deleted: list[str] = data.get("deleted", [])
    failed = [DeleteFailure(**entry) for entry in data.get("failed", [])]

    logger.info(
        "Delete batch completed",
        deleted_count=len(deleted),
        failed_count=len(failed),
    )

    return BulkDeleteResult(deleted=deleted, failed=failed)
