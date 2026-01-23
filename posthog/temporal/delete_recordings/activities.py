import json
from datetime import UTC, datetime
from urllib import parse
from uuid import uuid4

from django.conf import settings

import pytz
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
    tag_queries(product=Product.REPLAY, team_id=input.team_id)
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


@activity.defn(name="load-recordings-with-query")
async def load_recordings_with_query(input: RecordingsWithQueryInput) -> list[str]:
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

    delete_query = f"""
        DELETE FROM sharded_session_replay_events
        ON CLUSTER '{CLICKHOUSE_CLUSTER}'
        WHERE is_deleted = 1
          AND _timestamp < now() - INTERVAL {input.grace_period_days} DAY
    """

    logger.info("Executing delete query", query_id=query_id)
    async with get_client() as client:
        await client.execute_query(
            delete_query,
            query_id=query_id,
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
    """Call the recording API delete endpoint for each recording."""
    bind_contextvars(team_id=input.team_id, session_count=len(input.session_ids))
    logger = LOGGER.bind()
    logger.info("Deleting recordings via recording API")

    recording_api_url = settings.RECORDING_API_URL
    if not recording_api_url:
        raise RuntimeError("RECORDING_API_URL is not configured")

    deleted: list[str] = []
    not_found: list[str] = []
    already_deleted: list[str] = []
    errors: list[dict[str, str]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for session_id in input.session_ids:
            url = f"{recording_api_url}/api/projects/{input.team_id}/recordings/{session_id}"
            try:
                response = await client.delete(url)

                if response.status_code == 200:
                    deleted.append(session_id)
                elif response.status_code == 404:
                    not_found.append(session_id)
                elif response.status_code == 410:
                    already_deleted.append(session_id)
                else:
                    error_text = response.text
                    logger.warning(
                        "Recording API delete failed",
                        session_id=session_id,
                        status_code=response.status_code,
                        error=error_text,
                    )
                    errors.append({"session_id": session_id, "error": f"Status {response.status_code}: {error_text}"})
            except Exception as e:
                logger.warning("Recording API delete request failed", session_id=session_id, error=str(e))
                errors.append({"session_id": session_id, "error": str(e)})

    logger.info(
        "Delete batch completed",
        deleted_count=len(deleted),
        not_found_count=len(not_found),
        already_deleted_count=len(already_deleted),
        error_count=len(errors),
    )

    return BulkDeleteResult(
        deleted=deleted,
        not_found=not_found,
        already_deleted=already_deleted,
        errors=errors,
    )
