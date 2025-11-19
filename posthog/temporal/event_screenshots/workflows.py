from temporalio import workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.event_screenshots.types import GenerateEventScreenshotsInput


@workflow.defn(name="generate-event-screenshots")
class GenerateEventScreenshotsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> GenerateEventScreenshotsInput:
        """Parse input from the management command CLI."""
        return GenerateEventScreenshotsInput.model_validate_json(input[0])

    @workflow.run
    async def run(self, input: GenerateEventScreenshotsInput) -> None:
        """Generate screenshots for event definitions."""
        pass
