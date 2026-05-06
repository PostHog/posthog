"""Per-job workflows for evaluation clustering (Stage A sampler + Stage B clustering stub)."""

from datetime import timedelta

import temporalio.exceptions
from temporalio import workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.evaluation_clustering.constants import (
    CLUSTERING_WORKFLOW_NAME,
    SAMPLER_ACTIVITY_HEARTBEAT,
    SAMPLER_ACTIVITY_RETRY_POLICY,
    SAMPLER_ACTIVITY_SCHEDULE_TO_CLOSE,
    SAMPLER_ACTIVITY_TIMEOUT,
    SAMPLER_MAX_SAMPLES_PER_JOB,
    SAMPLER_WINDOW_MINUTES,
    SAMPLER_WINDOW_OFFSET_MINUTES,
    SAMPLER_WORKFLOW_NAME,
)
from posthog.temporal.llm_analytics.evaluation_clustering.models import (
    SamplerActivityInputs,
    SamplerWorkflowInputs,
    SamplerWorkflowResult,
)
from posthog.temporal.llm_analytics.evaluation_clustering.sampling import sample_and_embed_for_job_activity
from posthog.temporal.llm_analytics.trace_clustering.metrics import (
    record_clusters_generated,
    record_items_analyzed,
    record_noise_points,
)


@workflow.defn(name=SAMPLER_WORKFLOW_NAME)
class LLMAEvaluationSamplerWorkflow(PostHogWorkflow):
    """Hourly per-(team, eval ClusteringJob) sampler.

    Computes the sample window deterministically from workflow time and dispatches
    a single activity that runs the HogQL query and enqueues embeddings.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SamplerWorkflowInputs:
        # Primarily invoked as a child workflow with a typed dataclass; CLI fallback
        # mainly exists for manual replays.
        if not inputs:
            return SamplerWorkflowInputs(team_id=0, job_id="", job_name="")
        return SamplerWorkflowInputs(
            team_id=int(inputs[0]),
            job_id=inputs[1] if len(inputs) > 1 else "",
            job_name=inputs[2] if len(inputs) > 2 else "",
        )

    @workflow.run
    async def run(self, inputs: SamplerWorkflowInputs) -> SamplerWorkflowResult:
        now = workflow.now()
        if inputs.window_start and inputs.window_end:
            window_start = inputs.window_start
            window_end = inputs.window_end
        else:
            window_end_dt = now - timedelta(minutes=SAMPLER_WINDOW_OFFSET_MINUTES)
            window_start_dt = window_end_dt - timedelta(minutes=SAMPLER_WINDOW_MINUTES)
            window_start = window_start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            window_end = window_end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        max_samples = inputs.max_samples or SAMPLER_MAX_SAMPLES_PER_JOB
        run_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        result = await workflow.execute_activity(
            sample_and_embed_for_job_activity,
            SamplerActivityInputs(
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                job_name=inputs.job_name,
                run_ts=run_ts,
                window_start=window_start,
                window_end=window_end,
                max_samples=max_samples,
                event_filters=inputs.event_filters,
            ),
            start_to_close_timeout=SAMPLER_ACTIVITY_TIMEOUT,
            schedule_to_close_timeout=SAMPLER_ACTIVITY_SCHEDULE_TO_CLOSE,
            heartbeat_timeout=SAMPLER_ACTIVITY_HEARTBEAT,
            retry_policy=SAMPLER_ACTIVITY_RETRY_POLICY,
        )

        return SamplerWorkflowResult(
            team_id=result.team_id,
            job_id=result.job_id,
            sampled=result.sampled,
            embedded=result.embedded,
            window_start=window_start,
            window_end=window_end,
        )


# Replaced by the real Stage B implementation in the follow-up PR that adds
# the activities module; this whole class, its reuse of SamplerWorkflowInputs/Result,
# and the no-op run body go away at that point.
@workflow.defn(name=CLUSTERING_WORKFLOW_NAME)
class LLMAEvaluationClusteringWorkflow(PostHogWorkflow):
    """Daily per-job clustering workflow.

    Orchestrates five activities:

    1. Compute — fetch embeddings, HDBSCAN cluster, distances, 2D coords.
    2. Metadata — join evals to their linked generations for downstream use.
    3. Label — LangGraph agent over evaluator+verdict+reasoning snippets.
    4. Aggregates — operational (via linked generation) + eval-specific metrics.
    5. Emit — single ``$ai_evaluation_clusters`` event with everything baked in.

    Returns a ``SamplerWorkflowResult`` (reused for coordinator-side tallying)
    with ``sampled`` set to total items analyzed.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SamplerWorkflowInputs:
        # Delegate to the sampler's parser — both accept the same shape; the
        # stub only needs parse_inputs so Temporal can instantiate the workflow
        # when it's triggered manually. A dedicated ClusteringWorkflowInputs
        # type lands with the real 5-step pipeline in a follow-up PR.
        return LLMAEvaluationSamplerWorkflow.parse_inputs(inputs)

    @workflow.run
    async def run(self, inputs: SamplerWorkflowInputs) -> SamplerWorkflowResult:
        # Lazy imports inside the workflow keep numpy / sklearn / umap / langgraph
        # off the workflow-side import graph (Temporal doesn't like heavy I/O
        # libs reaching workflow code).
        from posthog.temporal.llm_analytics.evaluation_clustering.activities import (
            METADATA_LOOKBACK,
            ComputeEvaluationAggregatesInputs,
            EmitEvaluationClusterEventsInputs,
            EvaluationClusteringComputeInputs,
            FetchEvaluationMetadataInputs,
            GenerateEvaluationLabelsInputs,
            compute_evaluation_cluster_aggregates_activity,
            compute_item_labeling_metadata,
            emit_evaluation_cluster_events_activity,
            fetch_evaluation_metadata_activity,
            generate_evaluation_cluster_labels_activity,
            perform_evaluation_clustering_compute_activity,
        )
        from posthog.temporal.llm_analytics.trace_clustering.constants import (
            AGGREGATES_ACTIVITY_RETRY_POLICY,
            AGGREGATES_ACTIVITY_TIMEOUT,
            AGGREGATES_HEARTBEAT_TIMEOUT,
            AGGREGATES_SCHEDULE_TO_CLOSE_TIMEOUT,
            COMPUTE_ACTIVITY_RETRY_POLICY,
            COMPUTE_ACTIVITY_TIMEOUT,
            COMPUTE_HEARTBEAT_TIMEOUT,
            COMPUTE_SCHEDULE_TO_CLOSE_TIMEOUT,
            EMIT_ACTIVITY_RETRY_POLICY,
            EMIT_ACTIVITY_TIMEOUT,
            EMIT_HEARTBEAT_TIMEOUT,
            EMIT_SCHEDULE_TO_CLOSE_TIMEOUT,
            LLM_ACTIVITY_RETRY_POLICY,
            LLM_ACTIVITY_TIMEOUT,
            LLM_HEARTBEAT_TIMEOUT,
            LLM_SCHEDULE_TO_CLOSE_TIMEOUT,
        )

        now = workflow.now()
        window_end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        window_start = (now - METADATA_LOOKBACK).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 1. Compute — pass the workflow's window through so the embeddings
        # fetch uses the same time slice as the metadata fetch below. Without
        # this, activity-local datetime.now() can drift past the metadata
        # lookback and sample eval ids whose linked generations are already
        # out of range, producing clusters with unresolvable navigation.
        compute_result = await workflow.execute_activity(
            perform_evaluation_clustering_compute_activity,
            EvaluationClusteringComputeInputs(
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                job_name=inputs.job_name,
                window_start=window_start,
                window_end=window_end,
            ),
            start_to_close_timeout=COMPUTE_ACTIVITY_TIMEOUT,
            schedule_to_close_timeout=COMPUTE_SCHEDULE_TO_CLOSE_TIMEOUT,
            heartbeat_timeout=COMPUTE_HEARTBEAT_TIMEOUT,
            retry_policy=COMPUTE_ACTIVITY_RETRY_POLICY,
        )

        if compute_result.skip_reason or not compute_result.eval_ids:
            workflow.logger.info(
                "skipping eval clustering run",
                reason=compute_result.skip_reason,
                job_id=inputs.job_id,
            )
            return SamplerWorkflowResult(
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                sampled=0,
                embedded=0,
                window_start=window_start,
                window_end=window_end,
            )

        record_items_analyzed(len(compute_result.eval_ids), "evaluation")
        record_noise_points(compute_result.num_noise_points, "evaluation")

        # 2. Metadata
        metadata_result = await workflow.execute_activity(
            fetch_evaluation_metadata_activity,
            FetchEvaluationMetadataInputs(
                team_id=inputs.team_id,
                eval_ids=compute_result.eval_ids,
                window_start=window_start,
                window_end=window_end,
            ),
            start_to_close_timeout=COMPUTE_ACTIVITY_TIMEOUT,
            schedule_to_close_timeout=COMPUTE_SCHEDULE_TO_CLOSE_TIMEOUT,
            heartbeat_timeout=COMPUTE_HEARTBEAT_TIMEOUT,
            retry_policy=COMPUTE_ACTIVITY_RETRY_POLICY,
        )

        item_metadata = compute_item_labeling_metadata(compute_result)

        # 3. Labels (LangGraph agent)
        labels_result = await workflow.execute_activity(
            generate_evaluation_cluster_labels_activity,
            GenerateEvaluationLabelsInputs(
                team_id=inputs.team_id,
                eval_ids=compute_result.eval_ids,
                labels=compute_result.labels,
                item_metadata=item_metadata,
                centroid_coords_2d=compute_result.centroid_coords_2d,
                eval_metadata=metadata_result.metadata,
                window_start=window_start,
                window_end=window_end,
            ),
            start_to_close_timeout=LLM_ACTIVITY_TIMEOUT,
            schedule_to_close_timeout=LLM_SCHEDULE_TO_CLOSE_TIMEOUT,
            heartbeat_timeout=LLM_HEARTBEAT_TIMEOUT,
            retry_policy=LLM_ACTIVITY_RETRY_POLICY,
        )

        # 4. Aggregates — best-effort on activity failure, but cancellation
        # must propagate so shutdowns/manual cancels don't silently continue
        # through emit (matches trace clustering's pattern).
        cluster_metrics: dict = {}
        try:
            cluster_metrics = await workflow.execute_activity(
                compute_evaluation_cluster_aggregates_activity,
                ComputeEvaluationAggregatesInputs(
                    eval_ids=compute_result.eval_ids,
                    labels=compute_result.labels,
                    eval_metadata=metadata_result.metadata,
                ),
                start_to_close_timeout=AGGREGATES_ACTIVITY_TIMEOUT,
                schedule_to_close_timeout=AGGREGATES_SCHEDULE_TO_CLOSE_TIMEOUT,
                heartbeat_timeout=AGGREGATES_HEARTBEAT_TIMEOUT,
                retry_policy=AGGREGATES_ACTIVITY_RETRY_POLICY,
            )
        except temporalio.exceptions.ActivityError as e:
            if isinstance(e.cause, temporalio.exceptions.CancelledError):
                raise
            workflow.logger.warning("eval aggregates activity failed; emitting without metrics")

        # 5. Emit
        emit_result = await workflow.execute_activity(
            emit_evaluation_cluster_events_activity,
            EmitEvaluationClusterEventsInputs(
                team_id=inputs.team_id,
                clustering_run_id=compute_result.clustering_run_id,
                window_start=window_start,
                window_end=window_end,
                eval_ids=compute_result.eval_ids,
                labels=compute_result.labels,
                centroids=compute_result.centroids,
                distances=compute_result.distances,
                coords_2d=compute_result.coords_2d,
                centroid_coords_2d=compute_result.centroid_coords_2d,
                cluster_labels=labels_result.cluster_labels,
                eval_metadata=metadata_result.metadata,
                job_id=inputs.job_id,
                job_name=inputs.job_name,
                cluster_metrics=cluster_metrics,
            ),
            start_to_close_timeout=EMIT_ACTIVITY_TIMEOUT,
            schedule_to_close_timeout=EMIT_SCHEDULE_TO_CLOSE_TIMEOUT,
            heartbeat_timeout=EMIT_HEARTBEAT_TIMEOUT,
            retry_policy=EMIT_ACTIVITY_RETRY_POLICY,
        )

        record_clusters_generated(emit_result.metrics.num_clusters, "evaluation")

        return SamplerWorkflowResult(
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            sampled=emit_result.metrics.total_items_analyzed,
            embedded=emit_result.metrics.num_clusters,
            window_start=window_start,
            window_end=window_end,
        )
