from datetime import datetime, timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from posthog.dataclasses import frozen
    from posthog.temporal.common.base import PostHogWorkflow
    from posthog.temporal.common.utils import on_asyncify_pool

    from ..facade import api
    from ..facade.clustering_contracts import ClusteringRunContext, ClusteringRunRef, ClusteringRunUpdate
    from ..logic.clustering.constants import FIRST_RUN_SAMPLE_LIMIT, FIRST_RUN_WORKFLOW


@frozen
class ClusteringCountRequest:
    ref: ClusteringRunRef
    context: ClusteringRunContext
    start: datetime
    end: datetime
    prepared: bool


@activity.defn
async def clustering_run_context_activity(ref: ClusteringRunRef) -> ClusteringRunContext | None:
    return await on_asyncify_pool(api.clustering_run_context)(ref)


@activity.defn
async def update_clustering_run_activity(update: ClusteringRunUpdate) -> None:
    await on_asyncify_pool(api.update_clustering_run)(update)


@activity.defn
async def clustering_count_activity(request: ClusteringCountRequest) -> int:
    count = api.clustering_ready_items if request.prepared else api.clustering_eligible_evaluations
    return await on_asyncify_pool(count)(request.ref.team_id, request.context, request.start, request.end)


@workflow.defn(name=FIRST_RUN_WORKFLOW)
class ClusteringFirstRunWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ClusteringRunRef:
        return ClusteringRunRef(team_id=int(inputs[0]), run_id=inputs[1])

    async def context(self, ref: ClusteringRunRef) -> ClusteringRunContext | None:
        return await workflow.execute_activity(
            clustering_run_context_activity,
            ref,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def update(self, ref: ClusteringRunRef, status: str, **kwargs: Any) -> None:
        await workflow.execute_activity(
            update_clustering_run_activity,
            ClusteringRunUpdate(ref=ref, status=status, **kwargs),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_interval=timedelta(minutes=1)),
        )

    @workflow.run
    async def run(self, ref: ClusteringRunRef) -> None:
        try:
            for attempt in range(24):
                context = await self.context(ref)
                if context is None or not context.active:
                    return
                end = workflow.now()
                start = end - timedelta(days=context.lookback_days)
                payload = {
                    "team_id": ref.team_id,
                    "job_id": context.job_id,
                    "job_name": context.job_name,
                    "event_filters": context.event_filters,
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                }
                if context.analysis_level == "evaluation":
                    eligible = await workflow.execute_activity(
                        clustering_count_activity,
                        ClusteringCountRequest(ref=ref, context=context, start=start, end=end, prepared=False),
                        start_to_close_timeout=timedelta(minutes=3),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                else:
                    payload["analysis_level"] = context.analysis_level
                    items = await workflow.execute_activity(
                        "sample_items_in_window_activity",
                        {**payload, "max_items": context.minimum},
                        start_to_close_timeout=timedelta(minutes=3),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    eligible = len(items)
                if eligible < context.minimum:
                    await self.update(ref, "waiting", eligible_count=eligible)
                    await workflow.sleep(timedelta(minutes=30))
                    continue

                await self.update(ref, "preparing", eligible_count=eligible)
                is_evaluation = context.analysis_level == "evaluation"
                await workflow.execute_child_workflow(
                    "llma-evaluation-sampler" if is_evaluation else "llma-trace-summarization",
                    {**payload, ("max_samples" if is_evaluation else "max_items"): FIRST_RUN_SAMPLE_LIMIT},
                    id=f"{workflow.info().workflow_id}-prepare-{attempt}",
                    execution_timeout=timedelta(hours=2),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                for _ in range(60):
                    current = await self.context(ref)
                    if current is None or not current.active:
                        return
                    prepared = await workflow.execute_activity(
                        clustering_count_activity,
                        ClusteringCountRequest(
                            ref=ref, context=context, start=start, end=workflow.now(), prepared=True
                        ),
                        start_to_close_timeout=timedelta(minutes=3),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    await self.update(ref, "preparing", prepared_count=prepared)
                    if prepared >= context.minimum:
                        break
                    await workflow.sleep(timedelta(seconds=30))
                else:
                    await self.update(ref, "failed", failure_reason="preparation_incomplete")
                    return

                await self.update(ref, "clustering")
                cluster_payload = {**payload, "max_samples": FIRST_RUN_SAMPLE_LIMIT}
                if not is_evaluation:
                    del cluster_payload["window_start"]
                    del cluster_payload["window_end"]
                    cluster_payload["lookback_days"] = context.lookback_days
                result = await workflow.execute_child_workflow(
                    "llma-evaluation-clustering" if is_evaluation else "llma-trace-clustering",
                    cluster_payload,
                    id=f"{workflow.info().workflow_id}-cluster",
                    execution_timeout=timedelta(hours=2),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                current = await self.context(ref)
                if current is None or not current.active:
                    return
                analyzed = result["sampled"] if is_evaluation else result["metrics"]["total_items_analyzed"]
                if analyzed < context.minimum:
                    await self.update(ref, "failed", failure_reason="preparation_incomplete")
                    return
                count = result["embedded"] if is_evaluation else result["metrics"]["num_clusters"]
                await self.update(ref, "completed", cluster_count=count)
                return
            workflow.continue_as_new(ref)
        except Exception as error:
            await self.update(ref, "failed", failure_reason="processing_failed")
            raise ApplicationError("Clustering first run failed", non_retryable=True) from error


WORKFLOWS = [ClusteringFirstRunWorkflow]
ACTIVITIES = [clustering_run_context_activity, update_clustering_run_activity, clustering_count_activity]
