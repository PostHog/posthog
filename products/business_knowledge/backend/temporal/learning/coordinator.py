from __future__ import annotations

import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow

from .schemas import LearningCoordinatorInput, LearningCoordinatorOutput

with workflow.unsafe.imports_passed_through():
    from .activities.collect import collect_learning_evidence_activity
    from .workflow import BusinessKnowledgeLearningWorkflow


@workflow.defn(name="business-knowledge-learning-coordinator")
class BusinessKnowledgeLearningCoordinatorWorkflow(PostHogWorkflow):
    @workflow.run
    async def run(self, input: LearningCoordinatorInput) -> LearningCoordinatorOutput:
        collected = await workflow.execute_activity(
            collect_learning_evidence_activity,
            input,
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        started = 0
        skipped = 0
        for item in collected.items:
            child_id = BusinessKnowledgeLearningWorkflow.workflow_id_for(item)
            try:
                await workflow.start_child_workflow(
                    BusinessKnowledgeLearningWorkflow.run,
                    item,
                    id=child_id,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )
                started += 1
            except WorkflowAlreadyStartedError:
                workflow.logger.info(
                    "business_knowledge.learning.child_already_started",
                    extra={
                        "team_id": item.team_id,
                        "provider": item.evidence.provider,
                        "evidence_key": item.evidence.evidence_key,
                        "child_id": child_id,
                    },
                )
                skipped += 1
        return LearningCoordinatorOutput(
            eligible_count=len(collected.items),
            started_count=started,
            skipped_count=skipped,
        )

    @staticmethod
    def parse_inputs(inputs: list[str]) -> LearningCoordinatorInput:
        if not inputs:
            return LearningCoordinatorInput()
        return LearningCoordinatorInput(**json.loads(inputs[0]))
