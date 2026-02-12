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
        fetch_segments_activity,
        get_sessions_to_prime_activity,
        label_clusters_activity,
        match_clusters_activity,
        persist_reports_activity,
    )
    from posthog.temporal.ai.video_segment_clustering.models import (
        ClusterForLabeling,
        ClusteringWorkflowInputs,
        ClusterSegmentsActivityInputs,
        FetchSegmentsActivityInputs,
        LabelClustersActivityInputs,
        MatchClustersActivityInputs,
        PersistReportsActivityInputs,
        PrimeSessionEmbeddingsActivityInputs,
        WorkflowResult,
    )

    from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_UNDERSTANDING_MODEL


@workflow.defn(name="video-segment-clustering")
class VideoSegmentClusteringWorkflow(PostHogWorkflow):
    """Per-team workflow to cluster video segments and create SignalReports.

    This workflow orchestrates 6 activities:
    0. Prime: Run session summarization on recently-ended sessions to populate embeddings
    1. Fetch: Query recent video segments from ClickHouse
    2. Cluster: Clustering segments into groups, i.e. potential reports
    3. Match: Match clusters to existing SignalReports (deduplication)
    4. Label: Generate LLM-based labels for new clusters
    5. Persist: Create/update SignalReports and SignalReportArtefacts
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ClusteringWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return ClusteringWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: ClusteringWorkflowInputs) -> WorkflowResult:
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
            return WorkflowResult(
                team_id=inputs.team_id,
                segments_processed=None,
                clusters_found=0,
                reports_created=0,
                reports_updated=0,
                artefacts_created=0,
                success=True,
                error=None,
            )

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
            return WorkflowResult(
                team_id=inputs.team_id,
                segments_processed=len(segments),
                clusters_found=0,
                reports_created=0,
                reports_updated=0,
                artefacts_created=0,
                success=True,
                error=None,
            )

        # Activity 4: Match clusters to existing SignalReports
        matching_result = await workflow.execute_activity(
            match_clusters_activity,
            args=[
                MatchClustersActivityInputs(
                    team_id=inputs.team_id,
                    clusters=all_clusters,
                )
            ],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
                backoff_coefficient=2.0,
            ),
        )

        # Activity 5: Generate labels for NEW clusters only
        labeling_result = None
        if matching_result.new_clusters:
            clusters_for_labeling = [
                ClusterForLabeling(cluster_id=c.cluster_id, segment_ids=c.segment_ids)
                for c in matching_result.new_clusters
            ]

            labeling_result = await workflow.execute_activity(
                label_clusters_activity,
                args=[
                    LabelClustersActivityInputs(
                        team_id=inputs.team_id,
                        clusters=clusters_for_labeling,
                        segments=segments,
                    )
                ],
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=RetryPolicy(
                    maximum_attempts=2,
                    initial_interval=timedelta(seconds=5),
                    maximum_interval=timedelta(seconds=30),
                    backoff_coefficient=2.0,
                ),
            )

        # Filter out non-actionable clusters
        actionable_new_clusters = []
        if labeling_result:
            for cluster in matching_result.new_clusters:
                label = labeling_result.labels.get(cluster.cluster_id)
                if label and label.actionable:
                    actionable_new_clusters.append(cluster)

        # Activity 6: Persist reports and artefacts
        persist_result = await workflow.execute_activity(
            persist_reports_activity,
            args=[
                PersistReportsActivityInputs(
                    team_id=inputs.team_id,
                    new_clusters=actionable_new_clusters,
                    matched_clusters=matching_result.matched_clusters,
                    labels=labeling_result.labels if labeling_result else {},
                    segments=segments,
                    segment_to_cluster=clustering_result.segment_to_cluster,
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

        return WorkflowResult(
            team_id=inputs.team_id,
            segments_processed=len(segments),
            clusters_found=len(all_clusters),
            reports_created=persist_result.reports_created,
            reports_updated=persist_result.reports_updated,
            artefacts_created=persist_result.artefacts_created,
            success=True,
            error=None,
        )

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
