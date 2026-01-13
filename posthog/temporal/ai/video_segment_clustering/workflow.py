"""Per-team video segment clustering workflow."""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.ai.video_segment_clustering import constants
    from posthog.temporal.ai.video_segment_clustering.activities import (
        cluster_segments_activity,
        create_noise_clusters_activity,
        create_update_tasks_activity,
        fetch_recent_sessions_activity,
        fetch_segments_activity,
        generate_labels_activity,
        link_segments_activity,
        match_clusters_activity,
        summarize_sessions_activity,
    )
    from posthog.temporal.ai.video_segment_clustering.models import (
        ClusterForLabeling,
        ClusteringWorkflowInputs,
        ClusterSegmentsActivityInputs,
        CreateNoiseClustersActivityInputs,
        CreateUpdateTasksActivityInputs,
        FetchRecentSessionsActivityInputs,
        FetchSegmentsActivityInputs,
        GenerateLabelsActivityInputs,
        LinkSegmentsActivityInputs,
        MatchClustersActivityInputs,
        SummarizeSessionsActivityInputs,
        WorkflowResult,
    )


@workflow.defn(name="video-segment-clustering")
class VideoSegmentClusteringWorkflow:
    """Per-team workflow to cluster video segments and create Tasks.

    This workflow orchestrates activities to:
    0. Prime: Run session summarization on recently-ended sessions to populate embeddings
    1. Fetch: Query unprocessed video segments from ClickHouse
    2. Cluster: HDBSCAN clustering with PCA dimensionality reduction
    3. Handle noise: Create single-segment clusters for all unclustered segments
    4. Match: Match clusters to existing Tasks (deduplication)
    5. Label: Generate LLM-based labels for new clusters
    6. Create/Update: Create new Tasks and update existing ones
    7. Link: Create TaskSegmentLink records and update watermark
    """

    @workflow.run
    async def run(self, inputs: ClusteringWorkflowInputs) -> WorkflowResult:
        """Execute the video segment clustering workflow for a single team.

        Args:
            inputs: ClusteringWorkflowInputs with team_id and parameters

        Returns:
            WorkflowResult with processing metrics
        """
        try:
            # Step 0: Prime the document_embeddings table by running session summarization
            # on all recordings that finished in the timeframe
            workflow.logger.info(f"Fetching recent sessions for summarization priming (team {inputs.team_id})")

            recent_sessions_result = await workflow.execute_activity(
                fetch_recent_sessions_activity,
                args=[
                    FetchRecentSessionsActivityInputs(
                        team_id=inputs.team_id,
                        lookback_hours=inputs.lookback_hours,
                    )
                ],
                start_to_close_timeout=constants.FETCH_SESSIONS_ACTIVITY_TIMEOUT,
                retry_policy=constants.COMPUTE_ACTIVITY_RETRY_POLICY,
            )

            if recent_sessions_result.session_ids:
                workflow.logger.info(
                    f"Running summarization for {len(recent_sessions_result.session_ids)} sessions "
                    f"to prime document_embeddings"
                )

                summarization_result = await workflow.execute_activity(
                    summarize_sessions_activity,
                    args=[
                        SummarizeSessionsActivityInputs(
                            team_id=inputs.team_id,
                            session_ids=recent_sessions_result.session_ids,
                        )
                    ],
                    start_to_close_timeout=constants.SUMMARIZE_SESSIONS_ACTIVITY_TIMEOUT,
                    heartbeat_timeout=constants.SUMMARIZE_SESSIONS_ACTIVITY_TIMEOUT,
                    retry_policy=constants.SESSION_PRIMING_RETRY_POLICY,
                )

                workflow.logger.info(
                    f"Summarization priming complete: {summarization_result.sessions_summarized} summarized, "
                    f"{summarization_result.sessions_skipped} skipped, {summarization_result.sessions_failed} failed"
                )
            else:
                workflow.logger.info("No recent sessions found for summarization priming")

            # Activity 1: Fetch unprocessed segments (now includes newly summarized sessions)
            fetch_result = await workflow.execute_activity(
                fetch_segments_activity,
                args=[
                    FetchSegmentsActivityInputs(
                        team_id=inputs.team_id,
                        since_timestamp=None,  # Use clustering state watermark
                        lookback_hours=inputs.lookback_hours,
                    )
                ],
                start_to_close_timeout=constants.FETCH_ACTIVITY_TIMEOUT,
                retry_policy=constants.COMPUTE_ACTIVITY_RETRY_POLICY,
            )

            segments = fetch_result.segments

            # Check minimum segments threshold
            if len(segments) < inputs.min_segments:
                workflow.logger.info(
                    f"Skipping clustering: only {len(segments)} segments, " f"need at least {inputs.min_segments}"
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

            # Get document IDs for clustering
            document_ids = [s.document_id for s in segments]

            # Activity 2: Cluster segments (fetches embeddings from DB internally)
            clustering_result = await workflow.execute_activity(
                cluster_segments_activity,
                args=[
                    ClusterSegmentsActivityInputs(
                        team_id=inputs.team_id,
                        document_ids=document_ids,
                    )
                ],
                start_to_close_timeout=constants.CLUSTER_ACTIVITY_TIMEOUT,
                retry_policy=constants.COMPUTE_ACTIVITY_RETRY_POLICY,
            )

            # Handle noise segments - ALL noise segments become individual clusters
            all_clusters = list(clustering_result.clusters)
            segment_to_cluster = dict(clustering_result.segment_to_cluster)

            if clustering_result.noise_segment_ids:
                max_cluster_id = max((c.cluster_id for c in clustering_result.clusters), default=-1)

                # Activity 2b: Create single-segment clusters for noise segments
                single_segment_clusters = await workflow.execute_activity(
                    create_noise_clusters_activity,
                    args=[
                        CreateNoiseClustersActivityInputs(
                            team_id=inputs.team_id,
                            document_ids=clustering_result.noise_segment_ids,
                            starting_cluster_id=max_cluster_id + 1,
                        )
                    ],
                    start_to_close_timeout=constants.CLUSTER_ACTIVITY_TIMEOUT,
                    retry_policy=constants.COMPUTE_ACTIVITY_RETRY_POLICY,
                )
                all_clusters.extend(single_segment_clusters)

                # Update segment_to_cluster mapping for single-segment clusters
                for cluster in single_segment_clusters:
                    for doc_id in cluster.segment_ids:
                        segment_to_cluster[doc_id] = cluster.cluster_id

                workflow.logger.info(
                    f"Created {len(single_segment_clusters)} single-segment clusters for noise segments"
                )

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

            # Activity 3: Match clusters to existing Tasks
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

            # Activity 4: Generate labels for NEW clusters only (includes actionability check)
            labeling_result = None
            if matching_result.new_clusters:
                # Convert to lightweight cluster format (no centroid embeddings)
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

            # Activity 5: Create new Tasks and update existing ones
            task_result = await workflow.execute_activity(
                create_update_tasks_activity,
                args=[
                    CreateUpdateTasksActivityInputs(
                        team_id=inputs.team_id,
                        new_clusters=actionable_new_clusters,
                        matched_clusters=matching_result.matched_clusters,
                        labels=labeling_result.labels if labeling_result else {},
                        segments=segments,
                    )
                ],
                start_to_close_timeout=constants.TASK_ACTIVITY_TIMEOUT,
                retry_policy=constants.DB_ACTIVITY_RETRY_POLICY,
            )

            # Build cluster_to_task mapping
            cluster_to_task: dict[int, str] = {}
            # Map new actionable clusters to their new task IDs
            for i, cluster in enumerate(actionable_new_clusters):
                if i < len(task_result.task_ids):
                    cluster_to_task[cluster.cluster_id] = task_result.task_ids[i]
            # Map matched clusters to existing task IDs
            for match in matching_result.matched_clusters:
                cluster_to_task[match.cluster_id] = match.task_id

            # Activity 6: Link segments to Tasks and update watermark
            link_result = await workflow.execute_activity(
                link_segments_activity,
                args=[
                    LinkSegmentsActivityInputs(
                        team_id=inputs.team_id,
                        task_ids=task_result.task_ids,
                        segments=segments,
                        segment_to_cluster=segment_to_cluster,  # Use updated mapping with single-segment clusters
                        cluster_to_task=cluster_to_task,
                        latest_timestamp=fetch_result.latest_timestamp,
                    )
                ],
                start_to_close_timeout=constants.LINK_ACTIVITY_TIMEOUT,
                retry_policy=constants.DB_ACTIVITY_RETRY_POLICY,
            )

            return WorkflowResult(
                team_id=inputs.team_id,
                segments_processed=len(segments),
                clusters_found=len(all_clusters),  # Include single-segment clusters
                tasks_created=task_result.tasks_created,
                tasks_updated=task_result.tasks_updated,
                links_created=link_result.links_created,
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
