import asyncio
import dataclasses
from datetime import timedelta
import json
import uuid
import structlog
import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from django.conf import settings
from ee.hogai.session_summaries.constants import FAILED_SESSION_SUMMARIES_MIN_RATIO
from ee.session_recordings.session_summary.llm.consume import (
    get_llm_session_group_patterns_assignment,
    get_llm_session_group_patterns_extraction,
    get_llm_session_group_summary,
    get_llm_single_session_summary,
)
from ee.session_recordings.session_summary.patterns.output_data import SessionGroupSummaryPatternsList
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext, SingleSessionSummaryLlmInputs
from ee.session_recordings.session_summary.summarize_session_group import (
    generate_session_group_patterns_assignment_prompt,
    generate_session_group_patterns_extraction_prompt,
    generate_session_group_summary_prompt,
    remove_excessive_content_from_session_summary_for_llm,
)
from posthog import constants
from posthog.redis import get_client
from posthog.models.team.team import Team
from posthog.temporal.ai.session_summary.shared import (
    SingleSessionSummaryInputs,
    get_single_session_summary_llm_input_from_redis,
    fetch_session_data_activity,
)
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
    extra_summary_context: ExtraSummaryContext | None = None
    local_reads_prod: bool = False


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummarySingleSessionOutput:
    """Output after generating a single session summary to pass through to the next group summary activity"""

    session_summary_str: str
    redis_input_key: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummaryOfSummariesInputs:
    session_ids: list[str]
    session_summaries: list[SessionGroupSummarySingleSessionOutput]
    user_id: int
    extra_summary_context: ExtraSummaryContext | None = None


@temporalio.activity.defn
async def get_llm_single_session_summary_activity(inputs: SingleSessionSummaryInputs) -> str:
    """Summarize a single session in one call"""
    redis_client = get_client()
    llm_input = get_single_session_summary_llm_input_from_redis(
        redis_client=redis_client,
        redis_input_key=inputs.redis_input_key,
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
    # Not storing the summary in Redis yet, as for 30 sessions we should fit within Temporal memory limits
    # TODO: Store in Redis to avoid hitting memory limits with larger amount of sessions
    return SessionGroupSummarySingleSessionOutput(
        session_summary_str=session_summary_str,
        redis_input_key=inputs.redis_input_key,
    )


def _get_session_group_single_session_summaries_inputs_from_redis(
    redis_input_keys: list[str],
) -> list[SingleSessionSummaryLlmInputs]:
    redis_client = get_client()
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
    patterns: SessionGroupSummaryPatternsList,
    session_summaries_chunk: list[str],
    user_id: int,
    session_ids: list[str],
    extra_summary_context: ExtraSummaryContext | None,
) -> SessionGroupSummaryPatternsList | Exception:
    try:
        patterns_assignment_prompt = generate_session_group_patterns_assignment_prompt(
            patterns=patterns,
            session_summaries=session_summaries_chunk,
            extra_summary_context=extra_summary_context,
        )
        return await get_llm_session_group_patterns_assignment(
            prompt=patterns_assignment_prompt, user_id=user_id, session_ids=session_ids
        )
    except Exception as err:  # Activity retries exhausted
        # Let caller handle the error
        return err


async def _generate_patterns_assignments(
    patterns: SessionGroupSummaryPatternsList,
    session_summaries_chunks: list[list[str]],
    user_id: int,
    session_ids: list[str],
    extra_summary_context: ExtraSummaryContext | None,
) -> list[SessionGroupSummaryPatternsList]:
    patterns_assignments_list_of_lists = []
    tasks = {}
    async with asyncio.TaskGroup() as tg:
        for chunk_index, summaries_chunk in enumerate(session_summaries_chunks):
            tasks[chunk_index] = tg.create_task(
                _generate_patterns_assignments_per_chunk(
                    patterns=patterns,
                    session_summaries_chunk=summaries_chunk,
                    user_id=user_id,
                    session_ids=session_ids,
                    extra_summary_context=extra_summary_context,
                )
            )
    for chunk_index, task in tasks.items():
        res = task.result()
        if isinstance(res, Exception):
            temporalio.workflow.logger.warning(
                f"Patterns assignments generation failed for chunk from sessions ({session_ids}) for user {user_id}: {res}"
            )
            continue
        patterns_assignments_list_of_lists.append(res)
        # TODO: Remove after testing
        with open(f"patterns_assignments_chunk_{chunk_index}.yaml", "w") as f:
            f.write(res.model_dump_json(exclude_none=True))

    return patterns_assignments_list_of_lists


@temporalio.activity.defn
async def get_llm_session_group_summary_activity(inputs: SessionGroupSummaryOfSummariesInputs) -> str:
    """Summarize a group of sessions in one call"""
    # Remove excessive content (like UUIDs) from session summaries when using them as a context for group summaries (and not a final step)
    session_summaries_str = [
        remove_excessive_content_from_session_summary_for_llm(session_summary.session_summary_str)
        for session_summary in inputs.session_summaries
    ]

    # TODO: Rework as separate activities
    patterns_prompt = generate_session_group_patterns_extraction_prompt(
        session_summaries=session_summaries_str, extra_summary_context=inputs.extra_summary_context
    )
    # Extract patterns from session summaries through LLM
    patterns_extraction = await get_llm_session_group_patterns_extraction(
        prompt=patterns_prompt, user_id=inputs.user_id, session_ids=inputs.session_ids
    )

    # TODO: Remove after testing
    with open("patterns_extraction.yaml", "w") as f:
        f.write(patterns_extraction.model_dump_json(exclude_none=True))

    # Split sessions summaries into chunks of 10 sessions each
    # TODO: Define in constants after testing optimal chunk size quality-wise
    session_summaries_chunks = [session_summaries_str[i : i + 10] for i in range(0, len(session_summaries_str), 10)]
    patterns_assignments_list_of_lists = await _generate_patterns_assignments(
        patterns=patterns_extraction,
        session_summaries_chunks=session_summaries_chunks,
        user_id=inputs.user_id,
        session_ids=inputs.session_ids,
        extra_summary_context=inputs.extra_summary_context,
    )

    # Collect data from Redis on single session summaries to be able to enrich the patterns collected
    single_session_summaries_inputs = _get_session_group_single_session_summaries_inputs_from_redis(
        redis_input_keys=[session_summary.redis_input_key for session_summary in inputs.session_summaries]
    )

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
                redis_input_key = f"{inputs.redis_input_key_base}:{session_id}"
                single_session_input = SingleSessionSummaryInputs(
                    session_id=session_id,
                    user_id=inputs.user_id,
                    team_id=inputs.team_id,
                    redis_input_key=redis_input_key,
                    extra_summary_context=inputs.extra_summary_context,
                    local_reads_prod=inputs.local_reads_prod,
                )
                tasks[session_id] = tg.create_task(self._fetch_session_data(single_session_input)), single_session_input
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

    async def _run_summaries(
        self, inputs: list[SingleSessionSummaryInputs]
    ) -> dict[str, SessionGroupSummarySingleSessionOutput]:
        """
        Generate per-session summaries.
        """
        if not inputs:
            raise ApplicationError("No sessions to summarize for group summary")
        # Summarize all sessions
        summaries: dict[str, SessionGroupSummarySingleSessionOutput] = {}
        tasks = {}
        async with asyncio.TaskGroup() as tg:
            for session_input in inputs:
                # TODO: When stories summaries in Redis (>50) - rework to use tuples also
                # to have the same taskgroun function for both fetch/summarize tasks
                tasks[session_input.session_id] = tg.create_task(self._run_summary(session_input))
        for session_id, task in tasks.items():
            res = task.result()
            if isinstance(res, Exception):
                temporalio.workflow.logger.warning(
                    f"Session summary failed for group summary for session {session_id} "
                    f"for user {inputs[0].user_id} in team {inputs[0].team_id}: {res}"
                )
            else:
                summaries[session_id] = res
        # Fail the workflow if too many sessions failed to summarize
        if len(summaries) < len(inputs) * FAILED_SESSION_SUMMARIES_MIN_RATIO:
            session_ids = [s.session_id for s in inputs]
            exception_message = (
                f"Too many sessions failed to summarize, when summarizing {len(inputs)} sessions "
                f"({session_ids}) "
                f"for user {inputs[0].user_id} in team {inputs[0].team_id}"
            )
            temporalio.workflow.logger.error(exception_message)
            raise ApplicationError(exception_message)
        return summaries

    @temporalio.workflow.run
    async def run(self, inputs: SessionGroupSummaryInputs) -> str:
        session_inputs = await self._fetch_session_group_data(inputs)
        summaries = await self._run_summaries(session_inputs)

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
                session_ids=list(summaries.keys()),
                session_summaries=list(summaries.values()),
                user_id=inputs.user_id,
                extra_summary_context=inputs.extra_summary_context,
            ),
            start_to_close_timeout=timedelta(minutes=10),
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
    # Use shared identifier to be able to construct all the ids to check/debug
    shared_id = uuid.uuid4()
    # Prepare the input data
    redis_input_key_base = f"session-summary:group:get-input:{user_id}-{team.id}:{shared_id}"
    session_group_input = SessionGroupSummaryInputs(
        session_ids=session_ids,
        user_id=user_id,
        team_id=team.id,
        redis_input_key_base=redis_input_key_base,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
    )
    # Connect to Temporal and execute the workflow
    workflow_id = f"session-summary:group:{user_id}-{team.id}:{shared_id}"
    result = asyncio.run(_execute_workflow(inputs=session_group_input, workflow_id=workflow_id))
    return result
