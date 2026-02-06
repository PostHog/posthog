"""Workflow for ingestion acceptance tests."""

from datetime import timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.ingestion_acceptance_test.activities import run_ingestion_acceptance_tests
    from posthog.temporal.ingestion_acceptance_test.types import IngestionAcceptanceTestInput


@temporalio.workflow.defn(name="ingestion-acceptance-test")
class IngestionAcceptanceTestWorkflow(PostHogWorkflow):
    """Workflow that runs ingestion acceptance tests.

    Verifies that the ingestion pipeline is functioning correctly by
    capturing events and querying them back.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> IngestionAcceptanceTestInput:
        return IngestionAcceptanceTestInput.model_validate_json(inputs[0]) if inputs else IngestionAcceptanceTestInput()

    @temporalio.workflow.run
    async def run(self, inputs: IngestionAcceptanceTestInput) -> dict:
        """Execute ingestion acceptance tests.

        Returns:
            Dict containing test results with summary and individual test outcomes.
        """
        result = await temporalio.workflow.execute_activity(
            run_ingestion_acceptance_tests,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=1,
            ),
        )

        return result
