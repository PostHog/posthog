import asyncio
from datetime import timedelta
import json
import uuid
import structlog
import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from django.conf import settings
from ee.session_recordings.session_summary.llm.consume import get_llm_session_summary
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext
from posthog import constants
from posthog.redis import get_client
from posthog.models.team.team import Team
from posthog.temporal.ai.session_summary.shared import (
    SessionGroupSummaryInputs,
    SingleSessionSummaryInputs,
    get_single_session_summary_llm_input_from_redis,
    fetch_session_data_activity,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def get_llm_single_session_summary_activity(inputs: SingleSessionSummaryInputs) -> str:
    """Summarize a single session in one call"""
    redis_client = get_client()
    llm_input = get_single_session_summary_llm_input_from_redis(
        redis_client=redis_client,
        redis_input_key=inputs.redis_input_key,
    )
    # Get summary from LLM
    session_summary_str = await get_llm_session_summary(
        session_id=llm_input.session_id,
        user_pk=llm_input.user_pk,
        # Prompt
        summary_prompt=llm_input.summary_prompt,
        system_prompt=llm_input.system_prompt,
        # Mappings to enrich events
        allowed_event_ids=list(llm_input.simplified_events_mapping.keys()),
        simplified_events_mapping=llm_input.simplified_events_mapping,
        simplified_events_columns=llm_input.simplified_events_columns,
        url_mapping_reversed=llm_input.url_mapping_reversed,
        window_mapping_reversed=llm_input.window_mapping_reversed,
        # Session metadata
        session_start_time_str=llm_input.session_start_time_str,
        session_duration=llm_input.session_duration,
    )
    # Not storing the summary in Redis yet, as for 30 sessions we should fit within Temporal memory limits
    # TODO: Store in Redis to avoid hitting memory limits with larger amount of sessions
    return session_summary_str


@temporalio.workflow.defn(name="summarize-session-group")
class SummarizeSessionGroupWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SessionGroupSummaryInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SessionGroupSummaryInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: SessionGroupSummaryInputs) -> dict[str, str]:
        # Fetch data for each session and store in Redis
        session_inputs = []
        for session_id in inputs.session_ids:
            redis_input_key = f"{inputs.redis_input_key_base}:{session_id}"
            single_session_input = SingleSessionSummaryInputs(
                session_id=session_id,
                user_pk=inputs.user_pk,
                team_id=inputs.team_id,
                redis_input_key=redis_input_key,
                extra_summary_context=inputs.extra_summary_context,
                local_reads_prod=inputs.local_reads_prod,
            )
            await temporalio.workflow.execute_activity(
                fetch_session_data_activity,
                single_session_input,
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            session_inputs.append(single_session_input)
        # Summarize all sessions
        summaries = {}
        for session_input in session_inputs:
            summary = await temporalio.workflow.execute_activity(
                get_llm_single_session_summary_activity,
                session_input,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            summaries[session_input.session_id] = summary
        temporalio.workflow.logger.info(
            f"Successfully executed summarize-session-group workflow with id {temporalio.workflow.info().workflow_id}"
        )
        # TODO: Return summary of summaries instead
        return summaries


async def _execute_workflow(inputs: SessionGroupSummaryInputs, workflow_id: str) -> str:
    client = await async_connect()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    result = await client.execute_workflow(
        "summarize-session-group",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=constants.GENERAL_PURPOSE_TASK_QUEUE,
        retry_policy=retry_policy,
    )
    return result


def execute_summarize_session_group(
    session_ids: list[str],
    user_pk: int,
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
    redis_input_key_base = f"session-summary:group:get-input:{user_pk}-{team.id}:{shared_id}"
    session_group_input = SessionGroupSummaryInputs(
        session_ids=session_ids,
        user_pk=user_pk,
        team_id=team.id,
        redis_input_key_base=redis_input_key_base,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
    )
    # Connect to Temporal and execute the workflow
    workflow_id = f"session-summary:group:{user_pk}-{team.id}:{shared_id}"
    result = asyncio.run(_execute_workflow(inputs=session_group_input, workflow_id=workflow_id))
    return result
