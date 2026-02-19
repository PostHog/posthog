import json
from dataclasses import dataclass
from datetime import timedelta

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow


@dataclass
class RunBrowserLabTestWorkflowInput:
    team_id: int
    browser_lab_test_id: str
    browser_lab_test_run_id: str


@dataclass
class RunBrowserLabTestWorkflowOutput:
    success: bool
    error: str | None = None


@temporalio.workflow.defn(name="run-browser-lab-test")
class RunBrowserLabTestWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunBrowserLabTestWorkflowInput:
        loaded = json.loads(inputs[0])
        return RunBrowserLabTestWorkflowInput(
            team_id=loaded["team_id"],
            browser_lab_test_id=loaded["browser_lab_test_id"],
            browser_lab_test_run_id=loaded["browser_lab_test_run_id"],
        )

    @temporalio.workflow.run
    async def run(self, input: RunBrowserLabTestWorkflowInput) -> RunBrowserLabTestWorkflowOutput:
        from .activities import RunBrowserLabTestActivityInput, run_browser_lab_test_activity

        result = await workflow.execute_activity(
            run_browser_lab_test_activity,
            RunBrowserLabTestActivityInput(
                team_id=input.team_id,
                browser_lab_test_id=input.browser_lab_test_id,
                browser_lab_test_run_id=input.browser_lab_test_run_id,
                url="",
                steps=[],
            ),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        return RunBrowserLabTestWorkflowOutput(success=result.success, error=result.error)
