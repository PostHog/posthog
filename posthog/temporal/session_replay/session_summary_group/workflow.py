import uuid
import asyncio
import hashlib
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from math import ceil

from django.conf import settings

import structlog
import temporalio
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.redis import get_async_client
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect
from posthog.temporal.session_replay.session_summary.activities.capture_timing import (
    CaptureTimingInputs,
    capture_timing_activity,
)
from posthog.temporal.session_replay.session_summary.state import (
    StateActivitiesEnum,
    generate_state_id_from_session_ids,
    generate_state_key,
)
from posthog.temporal.session_replay.session_summary.types.inputs import SingleSessionSummaryInputs
from posthog.temporal.session_replay.session_summary.workflow import ensure_llm_single_session_summary
from posthog.temporal.session_replay.session_summary_group.activities import (
    assign_events_to_patterns_activity,
    combine_patterns_from_chunks_activity,
    extract_session_group_patterns_activity,
    fetch_session_batch_events_activity,
    split_session_summaries_into_chunks_for_patterns_extraction_activity,
)
from posthog.temporal.session_replay.session_summary_group.activities.group_patterns import (
    get_patterns_from_redis_outside_workflow,
)
from posthog.temporal.session_replay.session_summary_group.types import (
    SessionBatchFetchOutput,
    SessionGroupSummaryInputs,
    SessionGroupSummaryOfSummariesInputs,
    SessionGroupSummaryPatternsExtractionChunksInputs,
    SessionProgressStreamData,
    SessionStatusChange,
    SessionSummaryStreamUpdate,
    WorkflowProgress,
)

from ee.hogai.session_summaries.constants import (
    FAILED_PATTERNS_EXTRACTION_MIN_RATIO,
    FAILED_SESSION_SUMMARIES_MIN_RATIO,
    SESSION_GROUP_SUMMARIES_WORKFLOW_POLLING_INTERVAL_MS,
    SESSION_SUMMARIES_MODEL,
)
from ee.hogai.session_summaries.session.summarize_session import ExtraSummaryContext
from ee.hogai.session_summaries.session_group.patterns import EnrichedSessionGroupSummaryPatternsList
from ee.hogai.session_summaries.utils import logging_session_ids
from ee.models.session_summaries import SessionGroupSummary

logger = structlog.get_logger(__name__)


MAX_STATUS_HISTORY = 50


@temporalio.workflow.defn(name="summarize-session-group")
class SummarizeSessionGroupWorkflow(PostHogWorkflow):
    inputs_cls = SessionGroupSummaryInputs

    def __init__(self) -> None:
        super().__init__()
        self._total_sessions = 0
        self._processed_single_summaries = 0
        self._processed_patterns_extraction = 0
        # Initial state is watching sessions, as it's intended to always be the first step
        self._current_status: list[str] = [""]
        # Tracking the progress of the individual steps
        self._raw_patterns_extracted_keys: list[str] = []
        self._pattern_assignments_completed = 0
        # Structured per-session progress tracking
        self._session_statuses: dict[str, str] = {}
        self._current_phase: str = "fetching_data"

    @temporalio.workflow.query
    def get_current_status(self) -> list[str]:
        """Query handler to get the current progress of summary processing."""
        if len(self._current_status) > MAX_STATUS_HISTORY:
            # Ensure the status doesn't grow too large
            self._current_status = self._current_status[-MAX_STATUS_HISTORY:]
        return self._current_status

    @temporalio.workflow.query
    def get_raw_patterns_extraction_keys(self) -> list[str]:
        """Query handler to get keys of the current extracted patterns stored in Redis."""
        return self._raw_patterns_extracted_keys

    @temporalio.workflow.query
    def get_progress(self) -> WorkflowProgress:
        """Query handler to get structured progress data for the frontend widget."""
        return WorkflowProgress(
            session_statuses=dict(self._session_statuses),
            phase=self._current_phase,
            total_sessions=self._total_sessions,
            patterns_found=[],  # Pattern names are fetched from Redis by the polling loop
        )

    @temporalio.workflow.signal
    async def update_pattern_assignments_progress(self, sessions_completed: int) -> None:
        """Signal to update pattern assignment progress."""
        if sessions_completed <= 0:
            return
        self._pattern_assignments_completed += sessions_completed
        self._current_status.append(
            f"Generating a report from analyzed patterns and sessions. Almost there ({self._pattern_assignments_completed}/{self._total_sessions})"
        )

    @staticmethod
    async def _fetch_session_batch_data(inputs: SessionGroupSummaryInputs) -> SessionBatchFetchOutput | Exception:
        """
        Fetch and handle the session data for all sessions in batch to avoid one activity failing the whole group.
        The data is stored in Redis to avoid hitting Temporal memory limits, so activity returns nothing if successful.
        """
        try:
            fetch_result = await temporalio.workflow.execute_activity(
                fetch_session_batch_events_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return fetch_result
        except Exception as err:  # Activity retries exhausted
            # Let caller handle the error
            return err

    async def _fetch_session_group_data(self, inputs: SessionGroupSummaryInputs) -> list[SingleSessionSummaryInputs]:
        """Fetch DB data for all sessions in batch and return successful inputs."""
        if not inputs.session_ids:
            msg = f"No sessions to fetch data for group summary: {inputs}"
            temporalio.workflow.logger.error(msg, extra={"signals_type": "session-summaries"})
            raise ApplicationError(msg)
        # Fetch data for all sessions in a single batch
        fetch_result = await self._fetch_session_batch_data(inputs)
        if isinstance(fetch_result, Exception):
            msg = (
                f"Failed to fetch batch data from DB, when summarizing {len(inputs.session_ids)} "
                f"sessions ({inputs.session_ids}) for user {inputs.user_id} in team {inputs.team_id}"
            )
            temporalio.workflow.logger.error(
                f"Session batch data fetch failed for group summary for sessions {inputs.session_ids} "
                f"in team {inputs.team_id} for user {inputs.user_id}: {fetch_result}",
                extra={"team_id": inputs.team_id, "user_id": inputs.user_id, "signals_type": "session-summaries"},
            )
            raise ApplicationError(msg) from fetch_result
        # Log expected skips if any
        if fetch_result.expected_skip_session_ids:
            temporalio.workflow.logger.info(
                f"Skipped {len(fetch_result.expected_skip_session_ids)} sessions due to insufficient data "
                f"(too short or no events): {fetch_result.expected_skip_session_ids}",
                extra={"team_id": inputs.team_id, "user_id": inputs.user_id, "signals_type": "session-summaries"},
            )
        # Track skipped sessions in structured progress
        for sid in fetch_result.expected_skip_session_ids:
            self._session_statuses[sid] = "skipped"
        # Create SingleSessionSummaryInputs for each session
        session_inputs: list[SingleSessionSummaryInputs] = []
        for session_id in fetch_result.fetched_session_ids:
            self._session_statuses[session_id] = "queued"
            single_session_input = SingleSessionSummaryInputs(
                session_id=session_id,
                user_id=inputs.user_id,
                user_distinct_id_to_log=inputs.user_distinct_id_to_log,
                team_id=inputs.team_id,
                redis_key_base=inputs.redis_key_base,
                model_to_use=inputs.model_to_use,
                extra_summary_context=inputs.extra_summary_context,
                local_reads_prod=inputs.local_reads_prod,
                video_based=inputs.video_based,
                trigger_session_id=inputs.trigger_session_id,
            )
            session_inputs.append(single_session_input)
        # Update total to exclude skipped sessions so progress reflects actual work
        self._total_sessions = len(session_inputs)
        # Fail the workflow if too many sessions failed unexpectedly
        # Expected skips (too short, no events) don't count against the failure ratio
        summarizable_session_count = len(inputs.session_ids) - len(fetch_result.expected_skip_session_ids)
        min_required = ceil(summarizable_session_count * FAILED_SESSION_SUMMARIES_MIN_RATIO)
        if summarizable_session_count > 0 and min_required > len(session_inputs):
            extracted_session_ids = {s.session_id for s in session_inputs}
            all_skipped_ids = set(fetch_result.expected_skip_session_ids)
            unexpected_failures = list(set(inputs.session_ids) - extracted_session_ids - all_skipped_ids)
            exception_message = (
                f"Too many sessions failed to fetch data unexpectedly, "
                f"when summarizing {len(inputs.session_ids)} sessions. "
                f"Unexpected failures: {unexpected_failures}; "
                f"Expected skips: {fetch_result.expected_skip_session_ids}; "
                f"for user {inputs.user_id} in team {inputs.team_id}"
            )
            temporalio.workflow.logger.exception(
                exception_message,
                extra={"team_id": inputs.team_id, "user_id": inputs.user_id, "signals_type": "session-summaries"},
            )
            raise ApplicationError(exception_message)
        return session_inputs

    async def _run_summary(self, inputs: SingleSessionSummaryInputs) -> None | Exception:
        """
        Run and handle the summary for a single session to avoid one activity failing the whole group.
        Supports both regular event-based summarization and video-based summarization.
        """
        self._session_statuses[inputs.session_id] = "summarizing"
        try:
            # Generate session summary
            await ensure_llm_single_session_summary(inputs)
            # Keep track of processed summaries
            self._processed_single_summaries += 1
            self._session_statuses[inputs.session_id] = "summarized"
            self._current_status.append(
                f"Watching sessions ({self._processed_single_summaries}/{self._total_sessions})"
            )
            return None
        except Exception as err:  # Activity retries exhausted
            self._session_statuses[inputs.session_id] = "failed"
            # Let caller handle the error
            return err

    async def _run_summaries(self, inputs: list[SingleSessionSummaryInputs]) -> list[SingleSessionSummaryInputs]:
        """
        Generate per-session summaries.
        """
        if not inputs:
            msg = "No sessions to summarize for group summary"
            temporalio.workflow.logger.error(msg, extra={"signals_type": "session-summaries"})
            raise ApplicationError(msg)
        # Summarize all sessions
        tasks = {}
        async with asyncio.TaskGroup() as tg:
            for single_session_input in inputs:
                tasks[single_session_input.session_id] = (
                    tg.create_task(self._run_summary(single_session_input)),
                    single_session_input,
                )
        self._current_status.append(f"Watching sessions ({self._total_sessions}/{self._total_sessions})")
        successful_sessions: list[SingleSessionSummaryInputs] = []

        # Check summary generation results
        for session_id, (task, single_session_input) in tasks.items():
            res = task.result()
            if isinstance(res, Exception):
                temporalio.workflow.logger.warning(
                    f"Session summary failed for group summary for session {session_id} "
                    f"for user {inputs[0].user_id} in team {inputs[0].team_id}: {res}",
                    extra={
                        "session_id": session_id,
                        "user_id": inputs[0].user_id,
                        "team_id": inputs[0].team_id,
                        "signals_type": "session-summaries",
                    },
                )
            else:
                # Store only successful generations
                successful_sessions.append(single_session_input)

        # Fail the workflow if too many sessions failed to summarize
        if len(successful_sessions) / len(inputs) < FAILED_SESSION_SUMMARIES_MIN_RATIO:
            session_ids = [s.session_id for s in inputs]
            exception_message = (
                f"Too many sessions failed to summarize, when summarizing {len(inputs)} sessions "
                f"({logging_session_ids(session_ids)}) "
                f"for user {inputs[0].user_id} in team {inputs[0].team_id}"
            )
            temporalio.workflow.logger.error(
                exception_message,
                extra={"user_id": inputs[0].user_id, "team_id": inputs[0].team_id, "signals_type": "session-summaries"},
            )
            raise ApplicationError(exception_message)
        return successful_sessions

    async def _run_patterns_extraction_chunk(self, inputs: SessionGroupSummaryOfSummariesInputs) -> None | Exception:
        """
        Run and handle pattern extraction for a chunk of sessions to avoid one activity failing the whole group.
        """
        try:
            redis_output_key = await temporalio.workflow.execute_activity(
                extract_session_group_patterns_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            self._processed_patterns_extraction += len(inputs.single_session_summaries_inputs)
            self._current_status.append(
                f"Searching for behavior patterns in sessions ({self._processed_patterns_extraction}/{self._total_sessions})"
            )
            # Get a key of extracted patterns stored in Redis and append to out list
            if redis_output_key:
                self._raw_patterns_extracted_keys.append(redis_output_key)
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
        chunks: list[list[str]] = await temporalio.workflow.execute_activity(
            split_session_summaries_into_chunks_for_patterns_extraction_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        # If a single chunk is returned, use the activity directly, as it should cover all the sessions, so combination step is not needed
        if len(chunks) == 1:
            result = await self._run_patterns_extraction_chunk(inputs)
            self._processed_patterns_extraction += len(inputs.single_session_summaries_inputs)
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
                chunk_state_id = generate_state_id_from_session_ids(chunk_session_ids)
                chunk_summaries_input = SessionGroupSummaryOfSummariesInputs(
                    single_session_summaries_inputs=chunk_inputs,
                    user_id=inputs.user_id,
                    user_distinct_id_to_log=inputs.user_distinct_id_to_log,
                    team_id=inputs.team_id,
                    summary_title=inputs.summary_title,
                    model_to_use=inputs.model_to_use,
                    extra_summary_context=inputs.extra_summary_context,
                    redis_key_base=inputs.redis_key_base,
                    trigger_session_id=inputs.trigger_session_id,
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
                    f"Pattern extraction failed for chunk {chunk_redis_key} containing sessions {chunk_session_ids}: {res}",
                    extra={"signals_type": "session-summaries"},
                )
                continue
            # Store only chunks of sessions were extracted successfully
            redis_keys_of_chunks_to_combine.append(chunk_redis_key)
            session_ids_with_patterns_extracted.extend(chunk_session_ids)
        # Check failure ratio
        if ceil(len(chunks) * FAILED_PATTERNS_EXTRACTION_MIN_RATIO) > len(redis_keys_of_chunks_to_combine):
            msg = (
                f"Too many chunks failed during pattern extraction: "
                f"{len(chunks) - len(redis_keys_of_chunks_to_combine)}/{len(chunks)} chunks failed"
            )
            temporalio.workflow.logger.error(msg, extra={"signals_type": "session-summaries"})
            raise ApplicationError(msg)
        # If enough chunks succeeded - combine patterns extracted from chunks in a single list
        self._current_status.append("Combining similar behavior patterns into groups")
        await temporalio.workflow.execute_activity(
            combine_patterns_from_chunks_activity,
            SessionGroupSummaryPatternsExtractionChunksInputs(
                redis_keys_of_chunks_to_combine=redis_keys_of_chunks_to_combine,
                session_ids=session_ids_with_patterns_extracted,
                user_id=inputs.user_id,
                user_distinct_id_to_log=inputs.user_distinct_id_to_log,
                team_id=inputs.team_id,
                redis_key_base=inputs.redis_key_base,
                extra_summary_context=inputs.extra_summary_context,
                trigger_session_id=inputs.trigger_session_id,
            ),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return session_ids_with_patterns_extracted

    @temporalio.workflow.run
    async def run(self, inputs: SessionGroupSummaryInputs) -> str:
        start_time = temporalio.workflow.now()
        self._total_sessions = len(inputs.session_ids)
        # Get events data from the DB (or cache)
        self._current_phase = "fetching_data"
        self._current_status.append("Fetching session data from the database")
        db_session_inputs = await self._fetch_session_group_data(inputs)
        # Generate single-session summaries for each session
        self._current_phase = "watching_sessions"
        self._current_status.append(f"Watching sessions (0/{self._total_sessions})")
        summaries_session_inputs = await self._run_summaries(db_session_inputs)
        # Extract patterns from session summaries (with chunking if needed)
        self._current_phase = "extracting_patterns"
        self._current_status.append(f"Searching for behavior patterns in sessions (0/{self._total_sessions})")
        session_ids_to_process = await self._run_patterns_extraction(
            SessionGroupSummaryOfSummariesInputs(
                single_session_summaries_inputs=summaries_session_inputs,
                user_id=inputs.user_id,
                user_distinct_id_to_log=inputs.user_distinct_id_to_log,
                team_id=inputs.team_id,
                summary_title=inputs.summary_title,
                model_to_use=inputs.model_to_use,
                extra_summary_context=inputs.extra_summary_context,
                redis_key_base=inputs.redis_key_base,
                trigger_session_id=inputs.trigger_session_id,
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
        self._current_phase = "assigning_patterns"
        self._current_status.append("Generating a report from analyzed patterns and sessions. Almost there")
        patterns_assignments = await temporalio.workflow.execute_activity(
            assign_events_to_patterns_activity,
            SessionGroupSummaryOfSummariesInputs(
                single_session_summaries_inputs=single_session_summaries_inputs,
                user_id=inputs.user_id,
                user_distinct_id_to_log=inputs.user_distinct_id_to_log,
                team_id=inputs.team_id,
                summary_title=inputs.summary_title,
                model_to_use=inputs.model_to_use,
                extra_summary_context=inputs.extra_summary_context,
                redis_key_base=inputs.redis_key_base,
                trigger_session_id=inputs.trigger_session_id,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        duration_seconds = (temporalio.workflow.now() - start_time).total_seconds()
        await temporalio.workflow.execute_activity(
            capture_timing_activity,
            CaptureTimingInputs(
                distinct_id=inputs.user_distinct_id_to_log,
                team_id=inputs.team_id,
                session_id=inputs.session_ids[0] if inputs.session_ids else "",
                timing_type="group_session_flow",
                duration_seconds=duration_seconds,
                success=True,
                extra_properties={
                    "workflow_type": "group",
                    "session_count": len(inputs.session_ids),
                    "video_based": inputs.video_based,
                },
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return patterns_assignments


async def _wait_for_update() -> None:
    """Pause between polling to avoid hitting Temporal too often"""
    await asyncio.sleep(max(1, ceil(SESSION_GROUP_SUMMARIES_WORKFLOW_POLLING_INTERVAL_MS / 1000)))


async def _start_session_group_summary_workflow(
    inputs: SessionGroupSummaryInputs, workflow_id: str
) -> AsyncGenerator[
    tuple[
        SessionSummaryStreamUpdate,
        tuple[EnrichedSessionGroupSummaryPatternsList, str] | str | SessionProgressStreamData,
    ],
    None,
]:
    """Start the workflow and yield status updates until completion."""
    client = await async_connect()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))

    # Start the workflow instead of execute
    handle = await client.start_workflow(
        "summarize-session-group",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
        retry_policy=retry_policy,
    )

    # Track previous states to detect changes, starting with None to catch empty state as the step changes
    previous_pattern_keys: list[str] | None = None
    published_statuses: set[str] = set()
    previous_progress: WorkflowProgress | None = None

    # Poll for status
    while True:
        # Check workflow status
        workflow_description = await handle.describe()
        # Query the current activities status
        progress_status: list[str] = await handle.query("get_current_status")
        # Query structured progress data
        current_progress: WorkflowProgress = await handle.query("get_progress")
        # Query the intermediate data
        patterns_keys: list[str] = await handle.query("get_raw_patterns_extraction_keys")
        # Workflow completed - get and yield the final result
        if workflow_description.status == WorkflowExecutionStatus.COMPLETED:
            summary_id: str = await handle.result()
            # Fetch the summary from DB by id
            try:
                session_group_summary = await SessionGroupSummary.objects.aget(id=summary_id)
            except SessionGroupSummary.DoesNotExist:
                msg = f"SessionGroupSummary with id {summary_id} not found in DB after workflow {workflow_id} completed"
                logger.exception(msg, workflow_id=workflow_id, summary_id=summary_id, signals_type="session-summaries")
                raise ApplicationError(msg)
            # Parse the summary JSON into EnrichedSessionGroupSummaryPatternsList
            patterns = EnrichedSessionGroupSummaryPatternsList.model_validate_json(session_group_summary.summary)
            yield (
                SessionSummaryStreamUpdate.FINAL_RESULT,
                (patterns, summary_id),
            )
            break
        # Workflow failed - raise an exception
        elif workflow_description.status in (
            WorkflowExecutionStatus.FAILED,
            WorkflowExecutionStatus.CANCELED,
            WorkflowExecutionStatus.TERMINATED,
            WorkflowExecutionStatus.TIMED_OUT,
        ):
            msg = f"Workflow {workflow_id} failed with status: {workflow_description.status}"
            logger.error(msg, workflow_id=workflow_id, signals_type="session-summaries")
            raise ApplicationError(msg)
        # Workflow still running
        else:
            # Yield the current status for UI (backward-compatible logging)
            for status in progress_status:
                if status not in published_statuses:
                    yield (SessionSummaryStreamUpdate.UI_STATUS, status)
                    published_statuses.add(status)

            # Fetch pattern names from Redis for structured progress
            pattern_names: list[str] = []
            if patterns_keys != previous_pattern_keys:
                intermediate_patterns = await get_patterns_from_redis_outside_workflow(
                    redis_output_keys=patterns_keys,
                    redis_client=get_async_client(),
                )
                if intermediate_patterns:
                    pattern_names = [p.pattern_name for p in intermediate_patterns]
                    # Still yield patterns as UI_STATUS for backward compatibility
                    yield (
                        SessionSummaryStreamUpdate.UI_STATUS,
                        f"**Patterns found:**",
                    )
                    for pattern in intermediate_patterns:
                        yield (
                            SessionSummaryStreamUpdate.UI_STATUS,
                            f"- {pattern.pattern_name}",
                        )
                previous_pattern_keys = patterns_keys.copy()

            # Diff structured progress and yield SESSION_PROGRESS if anything changed
            has_changes = previous_progress is None or (
                current_progress["session_statuses"] != previous_progress["session_statuses"]
                or current_progress["phase"] != previous_progress["phase"]
            )
            if has_changes:
                # Collect status changes since last poll
                status_changes: list[SessionStatusChange] = []
                for sid, status in current_progress["session_statuses"].items():
                    if previous_progress is None or previous_progress["session_statuses"].get(sid) != status:
                        status_changes.append(SessionStatusChange(id=sid, status=status))
                completed_count = sum(
                    1 for s in current_progress["session_statuses"].values() if s in ("summarized", "failed")
                )
                progress_dict: SessionProgressStreamData = {
                    "type": "progress",
                    "status_changes": status_changes,
                    "phase": current_progress["phase"],
                    "completed_count": completed_count,
                    "total_count": current_progress["total_sessions"],
                    "patterns_found": pattern_names,
                }
                yield (SessionSummaryStreamUpdate.SESSION_PROGRESS, progress_dict)
                previous_progress = current_progress

            # Wait till the next polling
            await _wait_for_update()


def _generate_shared_id(session_ids: list[str]) -> str:
    """Generate a shared id for the group of sessions."""
    # Using session ids instead of random UUID to be able to check the data in Redis. Hex to avoid hitting workflow id limit.
    return hashlib.sha256("-".join(session_ids).encode()).hexdigest()[:16]


async def execute_summarize_session_group(
    session_ids: list[str],
    user: User,
    team: Team,
    min_timestamp: datetime,
    max_timestamp: datetime,
    summary_title: str | None,
    model_to_use: str = SESSION_SUMMARIES_MODEL,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
    video_based: bool = False,
    trigger_session_id: str | None = None,
) -> AsyncGenerator[
    tuple[
        SessionSummaryStreamUpdate,
        tuple[EnrichedSessionGroupSummaryPatternsList, str] | str | SessionProgressStreamData,
    ],
    None,
]:
    """
    Start the workflow and yield status updates and final summary for the group of sessions.
    """
    # Use shared identifier to be able to construct all the ids to check/debug.
    shared_id = _generate_shared_id(session_ids)
    # Prepare the input data
    redis_key_base = f"session-summary:group:{user.id}-{team.id}:{shared_id}"
    session_group_input = SessionGroupSummaryInputs(
        session_ids=session_ids,
        user_id=user.id,
        user_distinct_id_to_log=user.distinct_id,
        team_id=team.id,
        redis_key_base=redis_key_base,
        summary_title=summary_title,
        min_timestamp_str=min_timestamp.isoformat(),
        max_timestamp_str=max_timestamp.isoformat(),
        model_to_use=model_to_use,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
        video_based=video_based,
        trigger_session_id=trigger_session_id,
    )
    # Connect to Temporal and execute the workflow
    workflow_id = f"session-summary:group:{user.id}-{team.id}:{shared_id}:{uuid.uuid4()}"
    # Yield status updates and final result
    async for update in _start_session_group_summary_workflow(inputs=session_group_input, workflow_id=workflow_id):
        yield update
