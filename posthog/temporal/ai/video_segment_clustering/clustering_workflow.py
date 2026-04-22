"""Per-team session analysis workflow.

Triggers session summarization for recently-ended sessions. Signal emission for
issue-indicating segments happens inside each session's summarization workflow
(Activity 6a: emit_session_problem_signals_activity), so this workflow only orchestrates priming.
"""

import json
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.ai.video_segment_clustering.models import GetSessionsToPrimeResult
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.temporal.ai.video_segment_clustering.clustering_activities import get_sessions_to_prime_activity
    from posthog.temporal.ai.video_segment_clustering.models import (
        ClusteringWorkflowInputs,
        PrimeSessionEmbeddingsActivityInputs,
    )
    from posthog.temporal.session_replay.session_summary.summarize_session import SummarizeSingleSessionWorkflow
    from posthog.temporal.session_replay.session_summary.types.single import SingleSessionSummaryInputs

    from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_UNDERSTANDING_MODEL


@workflow.defn(name="video-segment-clustering")
class VideoSegmentClusteringWorkflow(PostHogWorkflow):
    """Per-team workflow to run session analysis and emit signals.

    Triggers session summarization for recently-ended sessions. Each summarization workflow emits signals
    for issue-indicating segments directly.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ClusteringWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return ClusteringWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: ClusteringWorkflowInputs) -> None:
        """Prime session summarization for a single team."""
        if inputs.skip_priming:
            workflow.logger.info(f"Skipping priming (team {inputs.team_id})")
            return None

        workflow.logger.info(f"Priming session embeddings (team {inputs.team_id})")

        # First, identify which sessions need summarization
        prime_info = await workflow.execute_activity(
            get_sessions_to_prime_activity,
            args=[
                PrimeSessionEmbeddingsActivityInputs(
                    team_id=inputs.team_id,
                    lookback_hours=inputs.lookback_hours,
                )
            ],
            start_to_close_timeout=timedelta(seconds=660),  # Should exceed HOGQL_INCREASED_MAX_EXECUTION_TIME (600s)
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
                backoff_coefficient=2.0,
            ),
        )
        # Then, run the child workflows to summarize those sessions
        await self.run_priming_child_workflows(team_id=inputs.team_id, prime_info=prime_info)
        return None

    async def run_priming_child_workflows(self, *, team_id: int, prime_info: GetSessionsToPrimeResult) -> None:
        sessions_summarized = 0
        sessions_failed = 0
        if prime_info.user_id is None:
            raise ApplicationError(f"No user with access to team {team_id} found for running summarization")
        user_id: int = prime_info.user_id
        if not prime_info.session_ids_to_summarize:
            workflow.logger.debug(f"Priming complete: {sessions_summarized} summarized, {sessions_failed} failed")
            return

        async def summarize_session(session_id: str) -> bool:
            redis_key_base = f"session-summary:single:{user_id}-{team_id}:{session_id}"
            handle: workflow.ChildWorkflowHandle = await workflow.start_child_workflow(
                "summarize-session",
                SingleSessionSummaryInputs(
                    session_id=session_id,
                    user_id=user_id,
                    user_distinct_id_to_log=prime_info.user_distinct_id,
                    team_id=team_id,
                    redis_key_base=redis_key_base,
                    model_to_use=DEFAULT_VIDEO_UNDERSTANDING_MODEL,
                    video_based=True,
                ),
                id=SummarizeSingleSessionWorkflow.workflow_id_for(team_id, session_id),
                task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                execution_timeout=timedelta(minutes=30),
                retry_policy=RetryPolicy(
                    maximum_attempts=1,  # No retries - if summarization fails, just skip this session
                ),
                parent_close_policy=workflow.ParentClosePolicy.REQUEST_CANCEL,
            )
            try:
                await handle
                return True
            except Exception as e:
                workflow.logger.warning(f"Session summarization skipped for {session_id}: {e}")
                return False

        results = await asyncio.gather(
            *(summarize_session(session_id) for session_id in prime_info.session_ids_to_summarize)
        )
        sessions_summarized = sum(1 for r in results if r)
        sessions_failed = sum(1 for r in results if not r)

        workflow.logger.debug(f"Priming complete: {sessions_summarized} summarized, {sessions_failed} failed")
