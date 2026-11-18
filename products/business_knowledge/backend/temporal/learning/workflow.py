from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.business_knowledge.backend.learning.contracts import EvidenceRef

from .schemas import AnalyzeLearningEvidenceInput, AnalyzeLearningEvidenceOutput, LearningWorkItem

with workflow.unsafe.imports_passed_through():
    from .activities.analyze import analyze_learning_evidence_activity


@workflow.defn(name="business-knowledge-learn")
class BusinessKnowledgeLearningWorkflow(PostHogWorkflow):
    @staticmethod
    def workflow_id_for(item: LearningWorkItem) -> str:
        return f"business-knowledge-learn-v1-{item.team_id}-{item.evidence.provider}-{item.evidence.evidence_key}"

    @workflow.run
    async def run(self, item: LearningWorkItem) -> AnalyzeLearningEvidenceOutput:
        return await workflow.execute_activity(
            analyze_learning_evidence_activity,
            AnalyzeLearningEvidenceInput(
                team_id=item.team_id,
                run_id=item.run_id,
                evidence=item.evidence,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    @staticmethod
    def parse_inputs(inputs: list[str]) -> LearningWorkItem:
        loaded = json.loads(inputs[0])
        evidence = loaded.pop("evidence")
        return LearningWorkItem(
            **loaded,
            evidence=EvidenceRef(
                **{
                    **evidence,
                    "ticket_id": UUID(evidence["ticket_id"]),
                    "resolution_comment_id": UUID(evidence["resolution_comment_id"]),
                    "revision_at": datetime.fromisoformat(evidence["revision_at"]),
                }
            ),
        )
