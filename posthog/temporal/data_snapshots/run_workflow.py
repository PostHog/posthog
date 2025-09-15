import json
import typing
import dataclasses

import temporalio.common
import temporalio.activity
import temporalio.workflow
import temporalio.exceptions

from posthog.temporal.common.base import PostHogWorkflow


@dataclasses.dataclass
class SnapshotWorkflowInputs:
    team_id: int
    saved_query_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "saved_query_id": self.saved_query_id,
        }


@temporalio.workflow.defn(name="data-modeling-run")
class SnapshotWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SnapshotWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SnapshotWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: SnapshotWorkflowInputs):
        """Run the snapshot workflow."""
