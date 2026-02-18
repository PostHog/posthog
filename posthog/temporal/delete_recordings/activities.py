import json
from datetime import UTC, datetime
from urllib import parse
from uuid import uuid4

from django.conf import settings

import httpx
from structlog.contextvars import bind_contextvars
from temporalio import activity

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
    LoadRecordingError,
    LoadRecordingsPage,
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
async def load_recordings_with_person(input: RecordingsWithPersonInput) -> LoadRecordingsPage:
    bind_contextvars(distinct_ids=input.distinct_ids, team_id=input.team_id)
    tag_queries(product=Product.REPLAY, team_id=input.team_id)
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
    tag_queries(product=Product.REPLAY, team_id=input.team_id)
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
    tag_queries(product=Product.REPLAY, team_id=input.team_id)
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
        return BulkDeleteResult(deleted=[])

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
    failed_count = len(data.get("failed", []))

    logger.info(
        "Delete batch completed",
        deleted_count=len(deleted),
        failed_count=failed_count,
    )

    return BulkDeleteResult(deleted=deleted, failed_count=failed_count)
