from dataclasses import dataclass
from typing import (
    Optional,
)

from temporalio import workflow

from posthog.temporal.workflows.base import CommandableWorkflow


@dataclass
class SendAllOrgUsageReportsArgs:
    dry_run: bool = False
    at: Optional[str] = None
    capture_event_name: Optional[str] = None
    skip_capture_event: bool = False
    only_organization_id: Optional[str] = None


@workflow.defn(name="send-all-org-usage-reports")
class SendAllOrgUsageReportsWorkflow(CommandableWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SendAllOrgUsageReportsArgs:
        """Parse inputs from the management command CLI."""
        # todo: parse inputs
        return inputs[0]

    @workflow.run
    async def run(self, time: str):
        # todo: migrate logic here
        workflow.logger.info("Done 🎉")
