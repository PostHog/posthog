"""Per-job workflows for evaluation clustering (Stage A sampler real, Stage B clustering stub)."""

from datetime import timedelta

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
    """Stub for the daily per-job clustering workflow.

    The real Stage B pipeline (compute → metadata → label → aggregates → emit)
    lands alongside the activities module in a follow-up PR. Until then this
    workflow is registered so its name resolves on the worker, but the run is
    a no-op so an accidentally-scheduled invocation completes harmlessly.
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
        workflow.logger.info(
            "evaluation clustering workflow stub — Stage B pipeline not yet wired",
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )
        return SamplerWorkflowResult(
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            sampled=0,
            embedded=0,
            window_start="",
            window_end="",
        )
