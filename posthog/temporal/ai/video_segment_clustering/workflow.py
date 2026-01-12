"""Per-team video segment clustering workflow."""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.ai.video_segment_clustering.activities import (
        cluster_segments_activity,
        create_update_tasks_activity,
        fetch_segments_activity,
        generate_labels_activity,
        link_segments_activity,
        match_clusters_activity,
    )
    from posthog.temporal.ai.video_segment_clustering.clustering import create_single_segment_clusters
    from posthog.temporal.ai.video_segment_clustering.models import (
        ClusteringWorkflowInputs,
        CreateUpdateTasksActivityInputs,
        FetchSegmentsActivityInputs,
        GenerateLabelsActivityInputs,
        LinkSegmentsActivityInputs,
        MatchClustersActivityInputs,
        WorkflowResult,
    )
    from posthog.temporal.ai.video_segment_clustering.priority import enrich_segments_with_impact


@workflow.defn(name="video-segment-clustering")
class VideoSegmentClusteringWorkflow:
    """Per-team workflow to cluster video segments and create Tasks.

    This workflow orchestrates activities to:
    1. Fetch: Query unprocessed video segments from ClickHouse
    2. Cluster: HDBSCAN clustering with PCA dimensionality reduction
    3. Handle high-impact noise: Create single-segment clusters for impactful unclustered segments
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
        from posthog.temporal.ai.video_segment_clustering import constants

        try:
            # Activity 1: Fetch unprocessed segments
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

            # Enrich segments with impact data early (needed for high-impact noise detection)
            # This is a deterministic operation so it's safe in the workflow
            segments_with_impact = enrich_segments_with_impact(segments)
            impact_lookup = {swi.segment.document_id: swi for swi in segments_with_impact}

            # Activity 2: Cluster segments
            clustering_result = await workflow.execute_activity(
                cluster_segments_activity,
                args=[segments],
                start_to_close_timeout=constants.CLUSTER_ACTIVITY_TIMEOUT,
                retry_policy=constants.COMPUTE_ACTIVITY_RETRY_POLICY,
            )

            # Handle high-impact noise segments
            # Find noise segments with high impact that should become individual Tasks
            high_impact_noise_ids = [
                doc_id
                for doc_id in clustering_result.noise_segment_ids
                if impact_lookup.get(doc_id)
                and impact_lookup[doc_id].impact_score > constants.HIGH_IMPACT_NOISE_THRESHOLD
            ]

            # Combine regular clusters with single-segment clusters for high-impact noise
            all_clusters = list(clustering_result.clusters)
            segment_to_cluster = dict(clustering_result.segment_to_cluster)

            if high_impact_noise_ids:
                max_cluster_id = max((c.cluster_id for c in clustering_result.clusters), default=-1)
                single_segment_clusters = create_single_segment_clusters(
                    noise_segment_ids=high_impact_noise_ids,
                    segments=segments,
                    starting_cluster_id=max_cluster_id + 1,
                )
                all_clusters.extend(single_segment_clusters)

                # Update segment_to_cluster mapping for single-segment clusters
                for cluster in single_segment_clusters:
                    for doc_id in cluster.segment_ids:
                        segment_to_cluster[doc_id] = cluster.cluster_id

                workflow.logger.info(
                    f"Created {len(single_segment_clusters)} single-segment clusters " f"for high-impact noise segments"
                )

            if not all_clusters:
                workflow.logger.info("No clusters or high-impact segments found")
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

            # Activity 4: Generate labels for NEW clusters only
            labeling_result = None
            if matching_result.new_clusters:
                labeling_result = await workflow.execute_activity(
                    generate_labels_activity,
                    args=[
                        GenerateLabelsActivityInputs(
                            team_id=inputs.team_id,
                            clusters=matching_result.new_clusters,
                            segments=segments,
                        )
                    ],
                    start_to_close_timeout=constants.LLM_ACTIVITY_TIMEOUT,
                    retry_policy=constants.LLM_ACTIVITY_RETRY_POLICY,
                )

            # Activity 5: Create new Tasks and update existing ones
            task_result = await workflow.execute_activity(
                create_update_tasks_activity,
                args=[
                    CreateUpdateTasksActivityInputs(
                        team_id=inputs.team_id,
                        new_clusters=matching_result.new_clusters,
                        matched_clusters=matching_result.matched_clusters,
                        labels=labeling_result.labels if labeling_result else {},
                        segments_with_impact=segments_with_impact,
                    )
                ],
                start_to_close_timeout=constants.TASK_ACTIVITY_TIMEOUT,
                retry_policy=constants.DB_ACTIVITY_RETRY_POLICY,
            )

            # Build cluster_to_task mapping
            cluster_to_task: dict[int, str] = {}
            # Map new clusters to their new task IDs
            for i, cluster in enumerate(matching_result.new_clusters):
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
                        segments_with_impact=segments_with_impact,
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
