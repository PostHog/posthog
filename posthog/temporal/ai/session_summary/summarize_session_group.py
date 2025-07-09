import asyncio
from datetime import timedelta
import hashlib
import json
from typing import cast
import uuid
import structlog
import temporalio
from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from django.conf import settings
from ee.hogai.session_summaries.constants import FAILED_SESSION_SUMMARIES_MIN_RATIO
from ee.session_recordings.session_summary.llm.consume import get_llm_single_session_summary
from ee.session_recordings.session_summary.patterns.output_data import EnrichedSessionGroupSummaryPatternsList
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext, SingleSessionSummaryLlmInputs
from posthog import constants
from posthog.models.team.team import Team
from posthog.temporal.ai.session_summary.activities.patterns import (
    assign_events_to_patterns_activity,
    extract_session_group_patterns_activity,
)
from posthog.temporal.ai.session_summary.shared import fetch_session_data_activity
from posthog.temporal.ai.session_summary.state import (
    get_data_class_from_redis,
    get_data_str_from_redis,
    get_redis_state_client,
    StateActivitiesEnum,
    store_data_in_redis,
)
from posthog.temporal.ai.session_summary.types.group import (
    SessionGroupSummaryInputs,
    SessionGroupSummaryOfSummariesInputs,
)
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect
from temporalio.exceptions import ApplicationError

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def get_llm_single_session_summary_activity(
    inputs: SingleSessionSummaryInputs,
) -> None:
    """Summarize a single session in one call and store/cache in Redis (to avoid hitting Temporal memory limits)"""
    redis_client, redis_input_key, redis_output_key = get_redis_state_client(
        key_base=inputs.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_DB_DATA,
        output_label=StateActivitiesEnum.SESSION_SUMMARY,
        state_id=inputs.session_id,
    )
    try:
        # Check if the summary is already in Redis. If it is - it's within TTL, so no need to re-generate it with LLM
        # TODO: Think about edge-cases like failed summaries
        await get_data_str_from_redis(
            redis_client=redis_client,
            redis_key=redis_output_key,
            label=StateActivitiesEnum.SESSION_SUMMARY,
        )
    except ValueError:
        # If not yet, or TTL expired - generate the summary with LLM
        llm_input = cast(
            SingleSessionSummaryLlmInputs,
            await get_data_class_from_redis(
                redis_client=redis_client,
                redis_key=redis_input_key,
                label=StateActivitiesEnum.SESSION_DB_DATA,
                target_class=SingleSessionSummaryLlmInputs,
            ),
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
            trace_id=temporalio.activity.info().workflow_id,
        )
        # Store the generated summary in Redis
        await store_data_in_redis(redis_client=redis_client, redis_key=redis_output_key, data=session_summary_str)
    # Returning nothing as the data is stored in Redis
    return None


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
        """Fetch DB data for each session and return successful inputs."""
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
                    redis_key_base=inputs.redis_key_base,
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

    @temporalio.workflow.run
    async def run(self, inputs: SessionGroupSummaryInputs) -> EnrichedSessionGroupSummaryPatternsList:
        db_session_inputs = await self._fetch_session_group_data(inputs)
        summaries_session_inputs = await self._run_summaries(db_session_inputs)

        # Extract patterns from session summaries
        await temporalio.workflow.execute_activity(
            extract_session_group_patterns_activity,
            SessionGroupSummaryOfSummariesInputs(
                single_session_summaries_inputs=summaries_session_inputs,
                user_id=inputs.user_id,
                extra_summary_context=inputs.extra_summary_context,
                redis_key_base=inputs.redis_key_base,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Assign events to patterns
        patterns_assignments = await temporalio.workflow.execute_activity(
            assign_events_to_patterns_activity,
            SessionGroupSummaryOfSummariesInputs(
                single_session_summaries_inputs=summaries_session_inputs,
                user_id=inputs.user_id,
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
    result: EnrichedSessionGroupSummaryPatternsList = await client.execute_workflow(
        "summarize-session-group",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=constants.MAX_AI_TASK_QUEUE,
        retry_policy=retry_policy,
    )
    return result


def _generate_shared_id(session_ids: list[str]) -> str:
    """Generate a shared id for the group of sessions."""
    # Using session ids instead of random UUID to be able to check the data in Redis. Hex to avoid hitting workflow id limit.
    return hashlib.sha256("-".join(session_ids).encode()).hexdigest()[:16]


def execute_summarize_session_group(
    session_ids: list[str],
    user_id: int,
    team: Team,
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
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
    )
    # Connect to Temporal and execute the workflow
    workflow_id = f"session-summary:group:{user_id}-{team.id}:{shared_id}:{uuid.uuid4()}"
    result = async_to_sync(_execute_workflow)(inputs=session_group_input, workflow_id=workflow_id)
    return result
