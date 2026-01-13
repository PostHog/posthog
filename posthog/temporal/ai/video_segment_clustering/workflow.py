"""Per-team video segment clustering workflow."""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.ai.video_segment_clustering import constants
    from posthog.temporal.ai.video_segment_clustering.activities import (
        cluster_segments_activity,
        fetch_segments_activity,
        generate_labels_activity,
        match_clusters_activity,
        persist_tasks_activity,
        prime_session_embeddings_activity,
    )
    from posthog.temporal.ai.video_segment_clustering.models import (
        ClusterForLabeling,
        ClusteringWorkflowInputs,
        ClusterSegmentsActivityInputs,
        FetchSegmentsActivityInputs,
        GenerateLabelsActivityInputs,
        MatchClustersActivityInputs,
        PersistTasksActivityInputs,
        PrimeSessionEmbeddingsActivityInputs,
        WorkflowResult,
    )


@workflow.defn(name="video-segment-clustering")
class VideoSegmentClusteringWorkflow:
    """Per-team workflow to cluster video segments and create Tasks.

    This workflow orchestrates 6 activities:
    1. Prime: Run session summarization on recently-ended sessions to populate embeddings
    2. Fetch: Query unprocessed video segments from ClickHouse
    3. Cluster: HDBSCAN clustering with noise handling
    4. Match: Match clusters to existing Tasks (deduplication)
    5. Label: Generate LLM-based labels for new clusters
    6. Persist: Create/update Tasks, links, and watermark
    """

    @workflow.run
    async def run(self, inputs: ClusteringWorkflowInputs) -> WorkflowResult:
        """Execute the video segment clustering workflow for a single team."""
        try:
            # Activity 1: Prime the document_embeddings table
            workflow.logger.info(f"Priming session embeddings (team {inputs.team_id})")

            priming_result = await workflow.execute_activity(
                prime_session_embeddings_activity,
                args=[
                    PrimeSessionEmbeddingsActivityInputs(
                        team_id=inputs.team_id,
                        lookback_hours=inputs.lookback_hours,
                    )
                ],
                start_to_close_timeout=constants.SUMMARIZE_SESSIONS_ACTIVITY_TIMEOUT,
                heartbeat_timeout=constants.SUMMARIZE_SESSIONS_ACTIVITY_TIMEOUT,
                retry_policy=constants.SESSION_PRIMING_RETRY_POLICY,
            )

            workflow.logger.info(
                f"Priming complete: {priming_result.sessions_summarized} summarized, "
                f"{priming_result.sessions_skipped} skipped, {priming_result.sessions_failed} failed"
            )

            # Activity 2: Fetch unprocessed segments
            fetch_result = await workflow.execute_activity(
                fetch_segments_activity,
                args=[
                    FetchSegmentsActivityInputs(
                        team_id=inputs.team_id,
                        since_timestamp=None,
                        lookback_hours=inputs.lookback_hours,
                    )
                ],
                start_to_close_timeout=constants.FETCH_ACTIVITY_TIMEOUT,
                retry_policy=constants.COMPUTE_ACTIVITY_RETRY_POLICY,
            )

            segments = fetch_result.segments

            if len(segments) < inputs.min_segments:
                workflow.logger.info(
                    f"Skipping clustering: only {len(segments)} segments, need at least {inputs.min_segments}"
                )
                return WorkflowResult(
                    team_id=inputs.team_id,
                    segments_processed=0,
                    clusters_found=0,
                    tasks_created=0,
                    tasks_updated=0,
                    links_created=0,
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
                        create_single_segment_clusters_for_noise=True,
                    )
                ],
                start_to_close_timeout=constants.CLUSTER_ACTIVITY_TIMEOUT,
                retry_policy=constants.COMPUTE_ACTIVITY_RETRY_POLICY,
            )

            all_clusters = clustering_result.clusters

            if not all_clusters:
                workflow.logger.info("No clusters found")
                return WorkflowResult(
                    team_id=inputs.team_id,
                    segments_processed=len(segments),
                    clusters_found=0,
                    tasks_created=0,
                    tasks_updated=0,
                    links_created=0,
                    success=True,
                    error=None,
                )

            # Activity 4: Match clusters to existing Tasks
            matching_result = await workflow.execute_activity(
                match_clusters_activity,
                args=[
                    MatchClustersActivityInputs(
                        team_id=inputs.team_id,
                        clusters=all_clusters,
                    )
                ],
                start_to_close_timeout=constants.MATCH_ACTIVITY_TIMEOUT,
                retry_policy=constants.COMPUTE_ACTIVITY_RETRY_POLICY,
            )

            # Activity 5: Generate labels for NEW clusters only
            labeling_result = None
            if matching_result.new_clusters:
                clusters_for_labeling = [
                    ClusterForLabeling(cluster_id=c.cluster_id, segment_ids=c.segment_ids)
                    for c in matching_result.new_clusters
                ]

                labeling_result = await workflow.execute_activity(
                    generate_labels_activity,
                    args=[
                        GenerateLabelsActivityInputs(
                            team_id=inputs.team_id,
                            clusters=clusters_for_labeling,
                            segments=segments,
                        )
                    ],
                    start_to_close_timeout=constants.LLM_ACTIVITY_TIMEOUT,
                    retry_policy=constants.LLM_ACTIVITY_RETRY_POLICY,
                )

            # Filter out non-actionable clusters
            actionable_new_clusters = []
            if labeling_result:
                for cluster in matching_result.new_clusters:
                    label = labeling_result.labels.get(cluster.cluster_id)
                    if label and label.actionable:
                        actionable_new_clusters.append(cluster)

            # Activity 6: Persist tasks, links, and watermark
            persist_result = await workflow.execute_activity(
                persist_tasks_activity,
                args=[
                    PersistTasksActivityInputs(
                        team_id=inputs.team_id,
                        new_clusters=actionable_new_clusters,
                        matched_clusters=matching_result.matched_clusters,
                        labels=labeling_result.labels if labeling_result else {},
                        segments=segments,
                        segment_to_cluster=clustering_result.segment_to_cluster,
                        latest_timestamp=fetch_result.latest_timestamp,
                    )
                ],
                start_to_close_timeout=constants.TASK_ACTIVITY_TIMEOUT,
                retry_policy=constants.DB_ACTIVITY_RETRY_POLICY,
            )

            return WorkflowResult(
                team_id=inputs.team_id,
                segments_processed=len(segments),
                clusters_found=len(all_clusters),
                tasks_created=persist_result.tasks_created,
                tasks_updated=persist_result.tasks_updated,
                links_created=persist_result.links_created,
                success=True,
                error=None,
            )

        except Exception as e:
            workflow.logger.error(f"Workflow failed for team {inputs.team_id}: {e}")
            return WorkflowResult(
                team_id=inputs.team_id,
                segments_processed=0,
                clusters_found=0,
                tasks_created=0,
                tasks_updated=0,
                links_created=0,
                success=False,
                error=str(e),
            )
