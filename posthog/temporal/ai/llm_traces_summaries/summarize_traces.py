import json
import uuid
import dataclasses
from datetime import timedelta

from django.conf import settings

import structlog
import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.schema import DateRange

from posthog.models.team.team import Team
from posthog.settings.temporal import MAX_AI_TASK_QUEUE
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect

from ee.hogai.llm_traces_summaries.summarize_traces import LLMTracesSummarizer

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True, kw_only=True)
class SummarizeLLMTracesInputs:
    date_to: str | None = None
    date_from: str | None = None
    team_id: int


@temporalio.activity.defn
async def summarize_llm_traces_activity(
    inputs: SummarizeLLMTracesInputs,
) -> None:
    """Summmarize and store embeddings for all LLM traces in the date range."""
    team = await database_sync_to_async(Team.objects.get)(id=inputs.team_id)
    summarizer = LLMTracesSummarizer(team=team)
    date_range = DateRange(date_from=inputs.date_from, date_to=inputs.date_to)
    await summarizer.summarize_traces_for_date_range(date_range=date_range)
    return None


@temporalio.workflow.defn(name="summarize-llm-traces")
class SummarizeLLMTracesWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SummarizeLLMTracesInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SummarizeLLMTracesInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: SummarizeLLMTracesInputs) -> None:
        await temporalio.workflow.execute_activity(
            summarize_llm_traces_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return None


async def execute_summarize_llm_traces(
    date_range: DateRange,
    team: Team,
) -> None:
    """
    Start the direct summarization workflow (no streaming) to stringify traces > generate summaries > generate embeddings and store everything.
    """
    workflow_id = f"llm-traces:summarize-traces:{date_range.date_from}:{date_range.date_to}:{team.id}:{uuid.uuid4()}"
    if not date_range.date_from and not date_range.date_to:
        raise ValueError("At least one of date_from or date_to must be provided when summarizing traces")
    client = await async_connect()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    await client.execute_workflow(
        "summarize-llm-traces",
        SummarizeLLMTracesInputs(date_to=date_range.date_to, date_from=date_range.date_from, team_id=team.id),
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=MAX_AI_TASK_QUEUE,
        retry_policy=retry_policy,
    )
