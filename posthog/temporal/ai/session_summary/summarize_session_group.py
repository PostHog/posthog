import asyncio
import dataclasses
from datetime import datetime, timedelta
import hashlib
import json
import uuid
import structlog
import temporalio
from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from django.conf import settings
from ee.hogai.session_summaries.constants import (
    FAILED_SESSION_SUMMARIES_MIN_RATIO,
    FAILED_PATTERNS_EXTRACTION_MIN_RATIO,
)
from ee.hogai.session_summaries.constants import FAILED_SESSION_SUMMARIES_MIN_RATIO, SESSION_SUMMARIES_SYNC_MODEL
from ee.hogai.session_summaries.session.input_data import add_context_and_filter_events, get_team
from ee.hogai.session_summaries.session_group.patterns import EnrichedSessionGroupSummaryPatternsList
from ee.hogai.session_summaries.session.summarize_session import (
    ExtraSummaryContext,
    SingleSessionSummaryLlmInputs,
    SessionSummaryDBData,
    prepare_data_for_single_session_summary,
    prepare_single_session_summary_input,
)
from posthog import constants
from posthog.models.team.team import Team
from posthog.schema import CachedSessionBatchEventsQueryResponse
from posthog.session_recordings.constants import DEFAULT_TOTAL_EVENTS_PER_QUERY
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.activities.patterns import (
    assign_events_to_patterns_activity,
    combine_patterns_from_chunks_activity,
    extract_session_group_patterns_activity,
    split_session_summaries_into_chunks_for_patterns_extraction_activity,
)
from posthog.hogql_queries.ai.session_batch_events_query_runner import (
    SessionBatchEventsQueryRunner,
    create_session_batch_events_query,
)
from posthog.temporal.ai.session_summary.state import (
    get_data_class_from_redis,
    generate_state_key,
    StateActivitiesEnum,
    store_data_in_redis,
)
from posthog.redis import get_async_client
from posthog.temporal.ai.session_summary.summarize_session import get_llm_single_session_summary_activity
from posthog.temporal.ai.session_summary.types.group import (
    SessionGroupSummaryInputs,
    SessionGroupSummaryOfSummariesInputs,
    SessionGroupSummaryPatternsExtractionChunksInputs,
)
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect
from temporalio.exceptions import ApplicationError

logger = structlog.get_logger(__name__)


def _get_db_events_per_page(
    session_ids: list[str], team: Team, min_timestamp_str: str, max_timestamp_str: str, page_size: int, offset: int
) -> CachedSessionBatchEventsQueryResponse:
    """Fetch events for multiple sessions in a single query and return the response. Separate function to run in a single db_sync_to_async call."""
    query = create_session_batch_events_query(
        session_ids=session_ids,
        after=min_timestamp_str,
        before=max_timestamp_str,
        max_total_events=page_size,
        offset=offset,
    )
    runner = SessionBatchEventsQueryRunner(query=query, team=team)
    response = runner.run()
    if not isinstance(response, CachedSessionBatchEventsQueryResponse):
        raise ValueError(
            f"Failed to fetch events for sessions {session_ids} in team {team.id} "
            f"when fetching batch events for group summary"
        )
    return response


def _get_db_columns(response_columns: list) -> list[str]:
    """Get the columns from the response and remove the properties prefix for backwards compatibility."""
    columns = [str(x).replace("properties.", "") for x in response_columns]
    return columns


@temporalio.activity.defn
async def fetch_session_batch_events_activity(
    inputs: SessionGroupSummaryInputs,
) -> list[str]:
    """Fetch batch events for multiple sessions using query runner and store per-session data in Redis. Returns a list of successful sessions."""
    redis_client = get_async_client()
    # Find sessions that were fetched successfully, already cached session are successful by default
    fetched_session_ids = []
    # Check which sessions already have cached data
    session_ids_to_fetch = []
    for session_id in inputs.session_ids:
        session_data_key = generate_state_key(
            key_base=inputs.redis_key_base,
            label=StateActivitiesEnum.SESSION_DB_DATA,
            state_id=session_id,
        )
        try:
            # Check if data for this session is already cached
            await get_data_class_from_redis(
                redis_client=redis_client,
                redis_key=session_data_key,
                label=StateActivitiesEnum.SESSION_DB_DATA,
                target_class=SingleSessionSummaryLlmInputs,
            )
            fetched_session_ids.append(session_id)
        except ValueError:
            # Session data not cached, need to fetch
            session_ids_to_fetch.append(session_id)
    # If all sessions already cached
    if not session_ids_to_fetch:
        return fetched_session_ids
    # Fetch metadata for all sessions at once
    # TODO: Decide if we need a query runner for this (as a follow-up)
    metadata_dict = await database_sync_to_async(SessionReplayEvents().get_group_metadata)(
        session_ids=session_ids_to_fetch,
        team_id=inputs.team_id,
        recordings_min_timestamp=datetime.fromisoformat(inputs.min_timestamp_str),
        recordings_max_timestamp=datetime.fromisoformat(inputs.max_timestamp_str),
    )
    # Fetch events for all uncached sessions
    team = await database_sync_to_async(get_team)(team_id=inputs.team_id)
    all_session_events: dict[str, list[tuple]] = {}  # session_id -> list of events
    columns, offset, page_size = None, 0, DEFAULT_TOTAL_EVENTS_PER_QUERY
    # Paginate
    while True:
        response = await database_sync_to_async(_get_db_events_per_page)(
            session_ids=session_ids_to_fetch,
            team=team,
            min_timestamp_str=inputs.min_timestamp_str,
            max_timestamp_str=inputs.max_timestamp_str,
            page_size=page_size,
            offset=offset,
        )
        # Store columns from first response (should be the same for all sessions)
        if columns is None:
            columns = _get_db_columns(response.columns)
        # Accumulate events for each session
        if response.session_events:
            for session_item in response.session_events:
                session_id = session_item.session_id
                if session_id not in all_session_events:
                    all_session_events[session_id] = []
                all_session_events[session_id].extend([tuple(event) for event in session_item.events])
        # Check if we have more pages
        if response.hasMore is not True:
            break
        offset += page_size
    # Store all per-session DB data in Redis
    for session_id in session_ids_to_fetch:
        session_events = all_session_events.get(session_id)
        if not session_events:
            temporalio.activity.logger.exception(
                f"No events found for session {session_id} in team {inputs.team_id} "
                f"when fetching batch events for group summary"
            )
            continue
        session_metadata = metadata_dict.get(session_id)
        if not session_metadata:
            temporalio.activity.logger.exception(
                f"No metadata found for session {session_id} in team {inputs.team_id} "
                f"when fetching batch events for group summary"
            )
            continue
        # Prepare the data to be used by the next activity
        filtered_columns, filtered_events = add_context_and_filter_events(columns, session_events)
        session_db_data = SessionSummaryDBData(
            session_metadata=session_metadata, session_events_columns=filtered_columns, session_events=filtered_events
        )
        summary_data = await prepare_data_for_single_session_summary(
            session_id=session_id,
            user_id=inputs.user_id,
            session_db_data=session_db_data,
            extra_summary_context=inputs.extra_summary_context,
        )
        if summary_data.error_msg is not None:
            # Skip sessions with errors (no events)
            continue
        input_data = prepare_single_session_summary_input(
            session_id=session_id,
            user_id=inputs.user_id,
            summary_data=summary_data,
            model_to_use=inputs.model_to_use,
        )
        # Store the input data in Redis
        session_data_key = generate_state_key(
            key_base=inputs.redis_key_base,
            label=StateActivitiesEnum.SESSION_DB_DATA,
            state_id=session_id,
        )
        input_data_str = json.dumps(dataclasses.asdict(input_data))
        fetched_session_ids.append(session_id)
        await store_data_in_redis(
            redis_client=redis_client,
            redis_key=session_data_key,
            data=input_data_str,
            label=StateActivitiesEnum.SESSION_DB_DATA,
        )
    # Returning nothing as the data is stored in Redis
    return fetched_session_ids


@temporalio.workflow.defn(name="summarize-session-group")
class SummarizeSessionGroupWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SessionGroupSummaryInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SessionGroupSummaryInputs(**loaded)

    @staticmethod
    async def _fetch_session_batch_data(inputs: SessionGroupSummaryInputs) -> list[str] | Exception:
        """
        Fetch and handle the session data for all sessions in batch to avoid one activity failing the whole group.
        The data is stored in Redis to avoid hitting Temporal memory limits, so activity returns nothing if successful.
        """
        try:
            fetched_session_ids = await temporalio.workflow.execute_activity(
                fetch_session_batch_events_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return fetched_session_ids
        except Exception as err:  # Activity retries exhausted
            # Let caller handle the error
            return err

    async def _fetch_session_group_data(self, inputs: SessionGroupSummaryInputs) -> list[SingleSessionSummaryInputs]:
        """Fetch DB data for all sessions in batch and return successful inputs."""
        if not inputs.session_ids:
            raise ApplicationError(f"No sessions to fetch data for group summary: {inputs}")
        # Fetch data for all sessions in a single batch
        fetch_result = await self._fetch_session_batch_data(inputs)
        if isinstance(fetch_result, Exception):
            temporalio.workflow.logger.error(
                f"Session batch data fetch failed for group summary for sessions {inputs.session_ids} "
                f"in team {inputs.team_id} for user {inputs.user_id}: {fetch_result}"
            )
            raise ApplicationError(
                f"Failed to fetch batch data from DB, when summarizing {len(inputs.session_ids)} "
                f"sessions ({inputs.session_ids}) for user {inputs.user_id} in team {inputs.team_id}"
            )
        # Create SingleSessionSummaryInputs for each session
        session_inputs: list[SingleSessionSummaryInputs] = []
        for session_id in fetch_result:
            single_session_input = SingleSessionSummaryInputs(
                session_id=session_id,
                user_id=inputs.user_id,
                team_id=inputs.team_id,
                redis_key_base=inputs.redis_key_base,
                model_to_use=inputs.model_to_use,
                extra_summary_context=inputs.extra_summary_context,
                local_reads_prod=inputs.local_reads_prod,
            )
            session_inputs.append(single_session_input)
        # Fail the workflow if too many sessions failed to fetch
        if len(session_inputs) < len(inputs.session_ids) * FAILED_SESSION_SUMMARIES_MIN_RATIO:
            extracted_session_ids = {s.session_id for s in session_inputs}
            exception_message = (
                f"Too many sessions failed to fetch data, when summarizing {len(inputs.session_ids)} sessions "
                f"({list(set(inputs.session_ids) - extracted_session_ids)}) "
                f"for user {inputs.user_id} in team {inputs.team_id}"
            )
            temporalio.workflow.logger.exception(exception_message)
            raise ApplicationError(exception_message)
        return session_inputs

    @staticmethod
    async def _run_summary(inputs: SingleSessionSummaryInputs) -> None | Exception:
        """
        Run and handle the summary for a single session to avoid one activity failing the whole group.
        """
        try:
            await temporalio.workflow.execute_activity(
                get_llm_single_session_summary_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return None
        except Exception as err:  # Activity retries exhausted
            # Let caller handle the error
            return err

    async def _run_summaries(self, inputs: list[SingleSessionSummaryInputs]) -> list[SingleSessionSummaryInputs]:
        """
        Generate per-session summaries.
        """
        if not inputs:
            raise ApplicationError("No sessions to summarize for group summary")
        # Summarize all sessions
        tasks = {}
        async with asyncio.TaskGroup() as tg:
            for single_session_input in inputs:
                # to have the same taskgroun function for both fetch/summarize tasks
                tasks[single_session_input.session_id] = (
                    tg.create_task(self._run_summary(single_session_input)),
                    single_session_input,
                )
        session_inputs: list[SingleSessionSummaryInputs] = []
        # Check summary generation results
        for session_id, (task, single_session_input) in tasks.items():
            res = task.result()
            if isinstance(res, Exception):
                temporalio.workflow.logger.warning(
                    f"Session summary failed for group summary for session {session_id} "
                    f"for user {inputs[0].user_id} in team {inputs[0].team_id}: {res}"
                )
            else:
                # Store only successful generations
                session_inputs.append(single_session_input)
        # Fail the workflow if too many sessions failed to summarize
        if len(session_inputs) < len(inputs) * FAILED_SESSION_SUMMARIES_MIN_RATIO:
            session_ids = [s.session_id for s in inputs]
            exception_message = (
                f"Too many sessions failed to summarize, when summarizing {len(inputs)} sessions "
                f"({session_ids}) "
                f"for user {inputs[0].user_id} in team {inputs[0].team_id}"
            )
            temporalio.workflow.logger.error(exception_message)
            raise ApplicationError(exception_message)
        return session_inputs

    @staticmethod
    async def _run_patterns_extraction_chunk(inputs: SessionGroupSummaryOfSummariesInputs) -> None | Exception:
        """
        Run and handle pattern extraction for a chunk of sessions to avoid one activity failing the whole group.
        """
        try:
            await temporalio.workflow.execute_activity(
                extract_session_group_patterns_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return None
        except Exception as err:  # Activity retries exhausted
            # Let caller handle the error
            return err

    async def _run_patterns_extraction(
        self,
        inputs: SessionGroupSummaryOfSummariesInputs,
    ) -> list[str] | None:
        """Extract patterns from session summaries using chunking if needed."""
        # Execute chunking activity to split sessions based on token count
        chunks = await temporalio.workflow.execute_activity(
            split_session_summaries_into_chunks_for_patterns_extraction_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        # If a single chunk is returned, use the activity directly, as it should cover all the sessions, so combination step is not needed
        if len(chunks) == 1:
            result = await self._run_patterns_extraction_chunk(inputs)
            if isinstance(result, Exception):
                raise result
            return None
        # Process chunks in parallel
        chunk_tasks = {}
        async with asyncio.TaskGroup() as tg:
            for chunk_session_ids in chunks:
                # Keep only session inputs related to sessions in this chunk
                chunk_inputs = [
                    input for input in inputs.single_session_summaries_inputs if input.session_id in chunk_session_ids
                ]
                chunk_state_id = ",".join(chunk_session_ids)
                chunk_summaries_input = SessionGroupSummaryOfSummariesInputs(
                    single_session_summaries_inputs=chunk_inputs,
                    user_id=inputs.user_id,
                    extra_summary_context=inputs.extra_summary_context,
                    redis_key_base=inputs.redis_key_base,
                )
                # Generate Redis key to store patterns extracted from sessions in this chunk
                chunk_redis_key = generate_state_key(
                    key_base=inputs.redis_key_base,
                    label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
                    state_id=chunk_state_id,
                )
                # Extract patterns through LLM (one activity per chunk)
                chunk_tasks[chunk_redis_key] = (
                    tg.create_task(self._run_patterns_extraction_chunk(chunk_summaries_input)),
                    chunk_session_ids,
                )
        # Check for failures
        redis_keys_of_chunks_to_combine = []
        session_ids_with_patterns_extracted = []
        for chunk_redis_key, (task, chunk_session_ids) in chunk_tasks.items():
            res = task.result()
            if isinstance(res, Exception):
                temporalio.workflow.logger.warning(
                    f"Pattern extraction failed for chunk {chunk_redis_key} containing sessions {chunk_session_ids}: {res}"
                )
                continue
            # Store only chunks of sessions were extracted successfully
            redis_keys_of_chunks_to_combine.append(chunk_redis_key)
            session_ids_with_patterns_extracted.extend(chunk_session_ids)
        # Check failure ratio
        if len(redis_keys_of_chunks_to_combine) < len(chunks) * FAILED_PATTERNS_EXTRACTION_MIN_RATIO:
            raise ApplicationError(
                f"Too many chunks failed during pattern extraction: "
                f"{len(chunks) - len(redis_keys_of_chunks_to_combine)}/{len(chunks)} chunks failed"
            )
        # If enough chunks succeeded - combine patterns extracted from chunks in a single list
        await temporalio.workflow.execute_activity(
            combine_patterns_from_chunks_activity,
            SessionGroupSummaryPatternsExtractionChunksInputs(
                redis_keys_of_chunks_to_combine=redis_keys_of_chunks_to_combine,
                session_ids=session_ids_with_patterns_extracted,
                user_id=inputs.user_id,
                redis_key_base=inputs.redis_key_base,
                extra_summary_context=inputs.extra_summary_context,
            ),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return session_ids_with_patterns_extracted

    @temporalio.workflow.run
    async def run(self, inputs: SessionGroupSummaryInputs) -> EnrichedSessionGroupSummaryPatternsList:
        db_session_inputs = await self._fetch_session_group_data(inputs)
        summaries_session_inputs = await self._run_summaries(db_session_inputs)
        # Extract patterns from session summaries (with chunking if needed)
        session_ids_to_process = await self._run_patterns_extraction(
            SessionGroupSummaryOfSummariesInputs(
                single_session_summaries_inputs=summaries_session_inputs,
                user_id=inputs.user_id,
                model_to_use=inputs.model_to_use,
                extra_summary_context=inputs.extra_summary_context,
                redis_key_base=inputs.redis_key_base,
            )
        )
        # If no session ids returned - then all the session ids got patterns extracted and cached successfully
        if session_ids_to_process is None:
            # Keeping all the initial sessions
            single_session_summaries_inputs = summaries_session_inputs
        # If specific ids returned - then patterns were extracted for session chunks, and combined,
        # so we need to continue specifically with sessions that succeeded
        else:
            # Keep only sessions that got patterns extracted
            single_session_summaries_inputs = [
                x for x in summaries_session_inputs if x.session_id in session_ids_to_process
            ]
        # Assign events to patterns
        patterns_assignments = await temporalio.workflow.execute_activity(
            assign_events_to_patterns_activity,
            SessionGroupSummaryOfSummariesInputs(
                single_session_summaries_inputs=single_session_summaries_inputs,
                user_id=inputs.user_id,
                model_to_use=inputs.model_to_use,
                extra_summary_context=inputs.extra_summary_context,
                redis_key_base=inputs.redis_key_base,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return patterns_assignments


async def _execute_workflow(
    inputs: SessionGroupSummaryInputs, workflow_id: str
) -> EnrichedSessionGroupSummaryPatternsList:
    """Execute the workflow and return the final group summary."""
    client = await async_connect()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    # Temporal returns EnrichedSessionGroupSummaryPatternsList deserialized to dict
    result_raw: dict = await client.execute_workflow(
        "summarize-session-group",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=constants.MAX_AI_TASK_QUEUE,
        retry_policy=retry_policy,
    )
    # Convert back to EnrichedSessionGroupSummaryPatternsList
    result = EnrichedSessionGroupSummaryPatternsList(**result_raw)
    return result


def _generate_shared_id(session_ids: list[str]) -> str:
    """Generate a shared id for the group of sessions."""
    # Using session ids instead of random UUID to be able to check the data in Redis. Hex to avoid hitting workflow id limit.
    return hashlib.sha256("-".join(session_ids).encode()).hexdigest()[:16]


def execute_summarize_session_group(
    session_ids: list[str],
    user_id: int,
    team: Team,
    min_timestamp: datetime,
    max_timestamp: datetime,
    model_to_use: str = SESSION_SUMMARIES_SYNC_MODEL,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
) -> EnrichedSessionGroupSummaryPatternsList:
    """
    Start the workflow and return the final summary for the group of sessions.
    """
    # Use shared identifier to be able to construct all the ids to check/debug.
    shared_id = _generate_shared_id(session_ids)
    # Prepare the input data
    redis_key_base = f"session-summary:group:{user_id}-{team.id}:{shared_id}"
    session_group_input = SessionGroupSummaryInputs(
        session_ids=session_ids,
        user_id=user_id,
        team_id=team.id,
        redis_key_base=redis_key_base,
        min_timestamp_str=min_timestamp.isoformat(),
        max_timestamp_str=max_timestamp.isoformat(),
        model_to_use=model_to_use,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
    )
    # Connect to Temporal and execute the workflow
    workflow_id = f"session-summary:group:{user_id}-{team.id}:{shared_id}:{uuid.uuid4()}"
    result = async_to_sync(_execute_workflow)(inputs=session_group_input, workflow_id=workflow_id)
    return result
