import asyncio
import dataclasses
from datetime import timedelta
import hashlib
import json
import uuid
from redis import Redis
import structlog
import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from django.conf import settings
from ee.hogai.session_summaries.constants import FAILED_SESSION_SUMMARIES_MIN_RATIO
from ee.session_recordings.session_summary.llm.consume import (
    get_llm_session_group_patterns_assignment,
    get_llm_session_group_patterns_extraction,
    get_llm_single_session_summary,
)
from ee.session_recordings.session_summary.patterns.output_data import (
    RawSessionGroupPatternAssignmentsList,
    RawSessionGroupSummaryPatternsList,
    combine_event_ids_mappings_from_single_session_summaries,
    combine_patterns_assignments_from_single_session_summaries,
    combine_patterns_ids_with_events_context,
    combine_patterns_with_events_context,
    load_session_summary_from_string,
)
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext, SingleSessionSummaryLlmInputs
from ee.session_recordings.session_summary.summarize_session_group import (
    generate_session_group_patterns_assignment_prompt,
    generate_session_group_patterns_extraction_prompt,
    remove_excessive_content_from_session_summary_for_llm,
)
from posthog import constants
from posthog.redis import get_client
from posthog.models.team.team import Team
from posthog.temporal.ai.session_summary.shared import (
    SESSION_SUMMARIES_DB_DATA_REDIS_TTL,
    SingleSessionSummaryInputs,
    compress_redis_data,
    get_single_session_summary_llm_input_from_redis,
    fetch_session_data_activity,
    get_single_session_summary_output_from_redis,
)
from posthog.temporal.ai.session_summary.state import generate_state_key, get_redis_state_client, StateActivitiesEnum
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect
from temporalio.exceptions import ApplicationError

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummaryInputs:
    """Workflow input to get summary for a group of sessions"""

    session_ids: list[str]
    user_id: int
    team_id: int
    redis_input_key_base: str
    redis_output_key_base: str
    extra_summary_context: ExtraSummaryContext | None = None
    local_reads_prod: bool = False


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummarySingleSessionOutput:
    """Output after generating a single session summary to pass through to the next group summary activity"""

    session_summary_str: str
    redis_input_key: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummaryOfSummariesInputs:
    single_session_summaries_inputs: list[SingleSessionSummaryInputs]
    user_id: int
    extra_summary_context: ExtraSummaryContext | None = None


@temporalio.activity.defn
async def get_llm_single_session_summary_activity(
    inputs: SingleSessionSummaryInputs,
) -> SessionGroupSummarySingleSessionOutput:
    """Summarize a single session in one call and store/cache in Redis (to avoid hitting Temporal memory limits)"""
    redis_client, redis_input_key, redis_output_key = get_redis_state_client(
        input_key_base=inputs.redis_input_key_base,
        input_label=StateActivitiesEnum.SESSION_DB_DATA,
        output_key_base=inputs.redis_output_key_base,
        output_label=StateActivitiesEnum.SESSION_SUMMARY,
        state_id=inputs.session_id,
    )
    try:
        # Check if the summary is already in Redis. If it is - it's within TTL, so no need to re-generate it with LLM
        # TODO: Think about edge-cases like failed summaries
        session_summary_str = get_single_session_summary_output_from_redis(
            redis_client=redis_client,
            redis_output_key=redis_output_key,
        )
    except ValueError:
        # If not yet, or TTL expired - generate the summary with LLM
        llm_input = get_single_session_summary_llm_input_from_redis(
            redis_client=redis_client, redis_input_key=redis_input_key
        )
        # Get summary from LLM
        session_summary_str = await get_llm_single_session_summary(
            session_id=llm_input.session_id,
            user_id=llm_input.user_id,
            # Prompt
            summary_prompt=llm_input.summary_prompt,
            system_prompt=llm_input.system_prompt,
            # Mappings to enrich events
            allowed_event_ids=list(llm_input.simplified_events_mapping.keys()),
            simplified_events_mapping=llm_input.simplified_events_mapping,
            event_ids_mapping=llm_input.event_ids_mapping,
            simplified_events_columns=llm_input.simplified_events_columns,
            url_mapping_reversed=llm_input.url_mapping_reversed,
            window_mapping_reversed=llm_input.window_mapping_reversed,
            # Session metadata
            session_start_time_str=llm_input.session_start_time_str,
            session_duration=llm_input.session_duration,
        )
        # Store the generated summary in Redis
        compressed_session_summary = compress_redis_data(session_summary_str)
        redis_client.setex(
            redis_output_key,
            SESSION_SUMMARIES_DB_DATA_REDIS_TTL,
            compressed_session_summary,
        )
    # Returning nothing as the data is stored in Redis
    return None


def _get_session_group_single_session_summaries_inputs_from_redis(
    redis_client: Redis,
    redis_input_keys: list[str],
) -> list[SingleSessionSummaryLlmInputs]:
    inputs = []
    for redis_input_key in redis_input_keys:
        llm_input = get_single_session_summary_llm_input_from_redis(
            redis_client=redis_client,
            redis_input_key=redis_input_key,
        )
        inputs.append(llm_input)
    return inputs


# TODO: Move to separate activities
async def _generate_patterns_assignments_per_chunk(
    patterns: RawSessionGroupSummaryPatternsList,
    session_summaries_chunk_str: list[str],
    user_id: int,
    session_ids: list[str],
    extra_summary_context: ExtraSummaryContext | None,
) -> RawSessionGroupPatternAssignmentsList | Exception:
    try:
        patterns_assignment_prompt = generate_session_group_patterns_assignment_prompt(
            patterns=patterns,
            session_summaries_str=session_summaries_chunk_str,
            extra_summary_context=extra_summary_context,
        )
        return await get_llm_session_group_patterns_assignment(
            prompt=patterns_assignment_prompt, user_id=user_id, session_ids=session_ids
        )
    except Exception as err:  # Activity retries exhausted
        # Let caller handle the error
        return err


async def _generate_patterns_assignments(
    patterns: RawSessionGroupSummaryPatternsList,
    session_summaries_chunks_str: list[list[str]],
    user_id: int,
    session_ids: list[str],
    extra_summary_context: ExtraSummaryContext | None,
) -> list[RawSessionGroupPatternAssignmentsList]:
    patterns_assignments_list_of_lists = []
    tasks = {}
    async with asyncio.TaskGroup() as tg:
        for chunk_index, summaries_chunk in enumerate(session_summaries_chunks_str):
            tasks[chunk_index] = tg.create_task(
                _generate_patterns_assignments_per_chunk(
                    patterns=patterns,
                    session_summaries_chunk_str=summaries_chunk,
                    user_id=user_id,
                    session_ids=session_ids,
                    extra_summary_context=extra_summary_context,
                )
            )
    for chunk_index, task in tasks.items():
        res = task.result()
        if isinstance(res, Exception):
            logger.warning(
                f"Patterns assignments generation failed for chunk from sessions ({session_ids}) for user {user_id}: {res}"
            )
            continue
        patterns_assignments_list_of_lists.append(res)
        # TODO: Remove after testing
        with open(f"patterns_assignments_chunk_{chunk_index}.json", "w") as f:
            f.write(res.model_dump_json(exclude_none=True))

    return patterns_assignments_list_of_lists


@temporalio.activity.defn
async def get_llm_session_group_summary_activity(inputs: SessionGroupSummaryOfSummariesInputs) -> str:
    """Summarize a group of sessions in one call"""
    redis_client = get_client()
    session_ids = list(dict.fromkeys([s.session_id for s in inputs.single_session_summaries_inputs]))
    total_sessions_count = len(session_ids)

    with open("session_ids_processed.json", "w") as f:
        f.write(json.dumps(session_ids))

    # Get session summaries from Redis
    session_summaries_str = [
        # TODO: Get values in batch?
        get_single_session_summary_output_from_redis(
            redis_client=redis_client,
            redis_output_key=s.redis_output_key,
        )
        for s in inputs.single_session_summaries_inputs
    ]
    # Remove excessive content (like UUIDs) from session summaries when using them as a context for group summaries (and not a final step)
    intermediate_session_summaries_str = [
        remove_excessive_content_from_session_summary_for_llm(session_summary_str)
        for session_summary_str in session_summaries_str
    ]

    # Single session summaries LLM inputs from Redis to be able to enrich the patterns collected
    single_session_summaries_llm_inputs = _get_session_group_single_session_summaries_inputs_from_redis(
        redis_client=redis_client,
        redis_input_keys=[
            generate_state_key(
                key_base=inputs.redis_input_key_base,
                label=StateActivitiesEnum.SESSION_SUMMARY,
                state_id=single_session_input.session_id,
            )
            for single_session_input in inputs.single_session_summaries_inputs
        ],
    )

    # session_summaries_str

    # Convert session summaries strings to objects to extract event-related data
    session_summaries = [
        load_session_summary_from_string(session_summary_str) for session_summary_str in session_summaries_str
    ]

    # TODO: Rework as separate activities
    patterns_extraction_prompt = generate_session_group_patterns_extraction_prompt(
        session_summaries_str=intermediate_session_summaries_str, extra_summary_context=inputs.extra_summary_context
    )
    # Extract patterns from session summaries through LLM
    patterns_extraction = await get_llm_session_group_patterns_extraction(
        prompt=patterns_extraction_prompt, user_id=inputs.user_id, session_ids=session_ids
    )

    # TODO: Remove after testing
    with open("patterns_extraction.json", "w") as f:
        f.write(patterns_extraction.model_dump_json(exclude_none=True))

    # Split sessions summaries into chunks of 10 sessions each
    # TODO: Define in constants after testing optimal chunk size quality-wise
    session_summaries_chunks_str = [
        intermediate_session_summaries_str[i : i + 10] for i in range(0, len(intermediate_session_summaries_str), 10)
    ]
    patterns_assignments_list_of_lists = await _generate_patterns_assignments(
        patterns=patterns_extraction,
        session_summaries_chunks_str=session_summaries_chunks_str,
        user_id=inputs.user_id,
        session_ids=session_ids,
        extra_summary_context=inputs.extra_summary_context,
    )

    # Combine event ids mappings from all the sessions to identify events and sessions assigned to patterns
    combined_event_ids_mappings = combine_event_ids_mappings_from_single_session_summaries(
        single_session_summaries_inputs=single_session_summaries_llm_inputs
    )
    with open("combined_event_ids_mappings.json", "w") as f:
        f.write(json.dumps(combined_event_ids_mappings))

    # Combine patterns assignments to have a single patter-to-event list
    combined_patterns_assignments = combine_patterns_assignments_from_single_session_summaries(
        patterns_assignments_list_of_lists=patterns_assignments_list_of_lists
    )
    with open("combined_patterns_assignments.json", "w") as f:
        f.write(json.dumps(combined_patterns_assignments))

    # Combine patterns ids with full event ids (from DB) and previous/next events in the segment per each assigned event
    pattern_id_to_event_context_mapping = combine_patterns_ids_with_events_context(
        combined_event_ids_mappings=combined_event_ids_mappings,
        combined_patterns_assignments=combined_patterns_assignments,
        session_summaries=session_summaries,
    )
    with open("pattern_event_ids_mapping.json", "w") as f:
        f.write(
            json.dumps(
                {k: [dataclasses.asdict(dv) for dv in v] for k, v in pattern_id_to_event_context_mapping.items()}
            )
        )

    # Combine patterns info (name, description, etc.) with enriched events context
    patterns_with_events_context = combine_patterns_with_events_context(
        patterns=patterns_extraction,
        pattern_id_to_event_context_mapping=pattern_id_to_event_context_mapping,
        total_sessions_count=total_sessions_count,
    )
    with open("patterns_with_events_context.json", "w") as f:
        f.write(patterns_with_events_context.model_dump_json(exclude_none=True))

    # TODO: Enable after testing
    # summary_prompt = generate_session_group_summary_prompt(
    #     session_summaries=session_summaries, extra_summary_context=inputs.extra_summary_context
    # )
    # # Get summary from LLM
    # summary_of_summaries = await get_llm_session_group_summary(
    #     prompt=summary_prompt, user_id=inputs.user_id, session_ids=inputs.session_ids
    # )
    # return summary_of_summaries


@temporalio.workflow.defn(name="summarize-session-group")
class SummarizeSessionGroupWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SessionGroupSummaryInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SessionGroupSummaryInputs(**loaded)

    @staticmethod
    async def _fetch_session_data(inputs: SingleSessionSummaryInputs) -> None | Exception:
        """
        Fetch and handle the session data for a single session to avoid one activity failing the whole group.
        The data is stored in Redis to avoid hitting Temporal memory limits, so activity returns nothing if successful.
        """
        try:
            # TODO: Instead of getting session data from DB one by one, we can optimize it by getting multiple sessions in one call
            await temporalio.workflow.execute_activity(
                fetch_session_data_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return None
        except Exception as err:  # Activity retries exhausted
            # Let caller handle the error
            return err

    async def _fetch_session_group_data(self, inputs: SessionGroupSummaryInputs) -> list[SingleSessionSummaryInputs]:
        if not inputs.session_ids:
            raise ApplicationError(f"No sessions to fetch data for group summary: {inputs}")
        # Fetch data for each session and store in Redis
        tasks = {}
        async with asyncio.TaskGroup() as tg:
            for session_id in inputs.session_ids:
                single_session_input = SingleSessionSummaryInputs(
                    session_id=session_id,
                    user_id=inputs.user_id,
                    team_id=inputs.team_id,
                    redis_input_key_base=inputs.redis_input_key_base,
                    redis_output_key_base=inputs.redis_output_key_base,
                    extra_summary_context=inputs.extra_summary_context,
                    local_reads_prod=inputs.local_reads_prod,
                )
                tasks[single_session_input.session_id] = (
                    tg.create_task(self._fetch_session_data(single_session_input)),
                    single_session_input,
                )
        session_inputs: list[SingleSessionSummaryInputs] = []
        # Check fetch results
        for session_id, (task, single_session_input) in tasks.items():
            res = task.result()
            if isinstance(res, Exception):
                temporalio.workflow.logger.warning(
                    f"Session data fetch failed for group summary for session {session_id} "
                    f"in team {inputs.team_id} for user {inputs.user_id}: {res}"
                )
            else:
                # Store only successful fetches
                session_inputs.append(single_session_input)
        # Fail the workflow if too many sessions failed to fetch
        if len(session_inputs) < len(inputs.session_ids) * FAILED_SESSION_SUMMARIES_MIN_RATIO:
            exception_message = (
                f"Too many sessions failed to fetch data from DB, when summarizing {len(inputs.session_ids)} "
                f"sessions ({inputs.session_ids}) for user {inputs.user_id} in team {inputs.team_id}"
            )
            temporalio.workflow.logger.error(exception_message)
            raise ApplicationError(exception_message)
        return session_inputs

    @staticmethod
    async def _run_summary(inputs: SingleSessionSummaryInputs) -> SessionGroupSummarySingleSessionOutput | Exception:
        """
        Run and handle the summary for a single session to avoid one activity failing the whole group.
        """
        try:
            return await temporalio.workflow.execute_activity(
                get_llm_single_session_summary_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
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
                # TODO: When stories summaries in Redis (>50) - rework to use tuples also
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

    @temporalio.workflow.run
    async def run(self, inputs: SessionGroupSummaryInputs) -> str:
        db_session_inputs = await self._fetch_session_group_data(inputs)
        summaries_session_inputs = await self._run_summaries(db_session_inputs)

        # # TODO: Remove after testing
        # from pathlib import Path

        # DATA_DIR = (
        #     Path(__file__).resolve().parents[4]
        #     / "playground/group_summaries_samples/testing_patterns/single-session-summaries"
        # ).resolve()
        # print("*" * 100)
        # print(DATA_DIR)
        # print("*" * 100)
        # # Iterate over all files in the directory, each file named as a session id, and contains the session summary
        # summaries: dict[str, str] = {}
        # for file in DATA_DIR.glob("*.json"):
        #     # Should be enough for the initial tests
        #     if len(summaries) >= 5:
        #         break
        #     with open(file, "r") as f:
        #         summaries[file.stem] = f.read()

        summary_of_summaries = await temporalio.workflow.execute_activity(
            get_llm_session_group_summary_activity,
            SessionGroupSummaryOfSummariesInputs(
                single_session_summaries_inputs=summaries_session_inputs,
                user_id=inputs.user_id,
                extra_summary_context=inputs.extra_summary_context,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return summary_of_summaries


async def _execute_workflow(inputs: SessionGroupSummaryInputs, workflow_id: str) -> str:
    client = await async_connect()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    result = await client.execute_workflow(
        "summarize-session-group",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=constants.MAX_AI_TASK_QUEUE,
        retry_policy=retry_policy,
    )
    return result


def execute_summarize_session_group(
    session_ids: list[str],
    user_id: int,
    team: Team,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
) -> str:
    """
    Start the workflow and return the final summary for the group of sessions.
    """
    # Use shared identifier to be able to construct all the ids to check/debug. Using session ids instead
    # of random UUID to be able to check the data in Redis. Hex to avoid hitting workflow id limit.
    # TODO: Move into a separate function
    shared_id = hashlib.sha256("-".join(session_ids).encode()).hexdigest()[:16]
    # Prepare the input data
    redis_input_key_base = f"session-summary:group:get-input:{user_id}-{team.id}:{shared_id}"
    redis_output_key_base = f"session-summary:group:single-session-summary-output:{user_id}-{team.id}:{shared_id}"
    session_group_input = SessionGroupSummaryInputs(
        session_ids=session_ids,
        user_id=user_id,
        team_id=team.id,
        redis_input_key_base=redis_input_key_base,
        redis_output_key_base=redis_output_key_base,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
    )
    # Connect to Temporal and execute the workflow
    workflow_id = f"session-summary:group:{user_id}-{team.id}:{shared_id}:{uuid.uuid4()}"
    result = asyncio.run(_execute_workflow(inputs=session_group_input, workflow_id=workflow_id))
    return result
