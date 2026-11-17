import uuid
from typing import Any

import pytest
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.salesforce_enrichment.workflow import (
    SalesforceEnrichmentAsyncWorkflow,
    SalesforceEnrichmentInputs,
    enrich_chunk_activity,
)


class TestEnrichmentWorkflow(SimpleTestCase):
    @parameterized.expand(
        [
            ("specific_domain", SalesforceEnrichmentInputs(specific_domain="example.com", score_icp_fit=True)),
            ("chunks", SalesforceEnrichmentInputs(max_chunks=1, score_icp_fit=True)),
        ]
    )
    @pytest.mark.asyncio
    async def test_workflow_passes_the_icp_fit_switch_to_the_job(
        self, _name: str, inputs: SalesforceEnrichmentInputs
    ) -> None:
        @activity.defn(name="cache_all_accounts_activity")
        async def cache_all_accounts() -> dict[str, Any]:
            return {"success": True, "total_accounts": 1}

        enrich = AsyncMock(return_value={"total_accounts_in_chunk": 0})
        task_queue = str(uuid.uuid4())

        with patch("posthog.temporal.salesforce_enrichment.workflow.enrich_accounts_async", new=enrich):
            async with await WorkflowEnvironment.start_time_skipping() as env:
                async with Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[SalesforceEnrichmentAsyncWorkflow],
                    activities=[enrich_chunk_activity, cache_all_accounts],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                ):
                    await env.client.execute_workflow(
                        SalesforceEnrichmentAsyncWorkflow.run, inputs, id=str(uuid.uuid4()), task_queue=task_queue
                    )

        assert enrich.call_args.kwargs["score_icp_fit"] is True
