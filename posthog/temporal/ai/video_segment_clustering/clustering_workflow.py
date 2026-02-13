"""Per-team video segment clustering workflow."""

import json
from datetime import timedelta

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.ai.video_segment_clustering.models import GetSessionsToPrimeResult
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
    from posthog.temporal.ai.video_segment_clustering.activities import (
        cluster_segments_activity,
        emit_signals_from_clusters_activity,
        fetch_segments_activity,
        get_sessions_to_prime_activity,
    )
    from posthog.temporal.ai.video_segment_clustering.models import (
        ClusteringWorkflowInputs,
        ClusterSegmentsActivityInputs,
        EmitSignalsActivityInputs,
        EmitSignalsResult,
        FetchSegmentsActivityInputs,
        PrimeSessionEmbeddingsActivityInputs,
    )

    from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_UNDERSTANDING_MODEL


@workflow.defn(name="video-segment-clustering")
class VideoSegmentClusteringWorkflow(PostHogWorkflow):
    """Per-team workflow to cluster video segments and emit signals.

    This workflow orchestrates activities:
    0. Prime: Run session summarization on recently-ended sessions to populate embeddings
    1. Fetch: Query recent video segments from ClickHouse
    2. Cluster: Clustering segments into groups
    3. Emit: Label clusters with LLM, then emit each as a signal via emit_signal()
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ClusteringWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return ClusteringWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: ClusteringWorkflowInputs) -> EmitSignalsResult | None:
        """Execute the video segment clustering workflow for a single team."""
        # Step 1: Prime the document_embeddings table with analysis of latest sessions
        prime_info = None
        if inputs.skip_priming:
            workflow.logger.info(f"Skipping priming (team {inputs.team_id})")
        else:
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
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                ),
            )
            # Then, run the child workflows to summarize those sessions
            await self.run_priming_child_workflows(team_id=inputs.team_id, prime_info=prime_info)

        # Activity 2: Fetch segments within lookback window
        fetch_result = await workflow.execute_activity(
            fetch_segments_activity,
            args=[
                FetchSegmentsActivityInputs(
                    team_id=inputs.team_id,
                    lookback_hours=inputs.lookback_hours,
                )
            ],
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
                backoff_coefficient=2.0,
            ),
        )

        segments = fetch_result.segments

        if len(segments) < inputs.min_segments:
            workflow.logger.info(
                f"Skipping clustering: only {len(segments)} segments, need at least {inputs.min_segments}"
            )
            return None

        document_ids = [s.document_id for s in segments]

        # Activity 3: Cluster segments (includes noise handling)
        clustering_result = await workflow.execute_activity(
            cluster_segments_activity,
            args=[
                ClusterSegmentsActivityInputs(
                    team_id=inputs.team_id,
                    document_ids=document_ids,
                )
            ],
            start_to_close_timeout=timedelta(seconds=180),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
                backoff_coefficient=2.0,
            ),
        )

        all_clusters = clustering_result.clusters

        if not all_clusters:
            workflow.logger.info("No clusters found")
            return None

        # Activity 4: Label clusters and emit as signals
        emit_result = await workflow.execute_activity(
            emit_signals_from_clusters_activity,
            args=[
                EmitSignalsActivityInputs(
                    team_id=inputs.team_id,
                    clusters=all_clusters,
                    segments=segments,
                )
            ],
            start_to_close_timeout=timedelta(seconds=300),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
                backoff_coefficient=2.0,
            ),
        )

        return emit_result

    async def run_priming_child_workflows(self, *, team_id: int, prime_info: GetSessionsToPrimeResult) -> None:
        sessions_summarized = 0
        sessions_failed = 0
        if prime_info.user_id is None:
            raise ApplicationError(f"No user with access to team {team_id} found for running summarization")
        if prime_info.session_ids_to_summarize:
            summarize_handles: dict[str, temporalio.workflow.ChildWorkflowHandle] = {}
            for session_id in prime_info.session_ids_to_summarize:
                redis_key_base = f"session-summary:single:{prime_info.user_id}-{team_id}:{session_id}"
                handle = await temporalio.workflow.start_child_workflow(
                    "summarize-session",
                    SingleSessionSummaryInputs(
                        session_id=session_id,
                        user_id=prime_info.user_id,
                        user_distinct_id_to_log=prime_info.user_distinct_id,
                        team_id=team_id,
                        redis_key_base=redis_key_base,
                        model_to_use=DEFAULT_VIDEO_UNDERSTANDING_MODEL,
                        video_validation_enabled="full",
                    ),
                    id=f"session-summary:single:direct:{team_id}:{session_id}:{prime_info.user_id}:{workflow.uuid4()}",
                    execution_timeout=timedelta(minutes=30),
                    retry_policy=RetryPolicy(
                        maximum_attempts=1,  # No retries - if summarization, just skip this session
                    ),
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.REQUEST_CANCEL,
                )
                summarize_handles[session_id] = handle

            # Wait for all summarization child workflows to complete, skipping failures
            for session_id, handle in summarize_handles.items():
                try:
                    await handle
                    sessions_summarized += 1
                except Exception as e:
                    sessions_failed += 1
                    workflow.logger.warning(f"Session summarization skipped for {session_id}: {e}")

        workflow.logger.debug(f"Priming complete: {sessions_summarized} summarized, {sessions_failed} failed")
