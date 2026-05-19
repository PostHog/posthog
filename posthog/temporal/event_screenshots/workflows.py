from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.event_screenshots.activities import (
    load_event_sessions,
    load_event_types,
    store_event_screenshot,
    take_event_screenshot,
)
from posthog.temporal.event_screenshots.types import GenerateEventScreenshotsInput, TakeEventScreenshotInput


@workflow.defn(name="generate-event-screenshots")
class GenerateEventScreenshotsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> GenerateEventScreenshotsInput:
        """Parse input from the management command CLI."""
        return GenerateEventScreenshotsInput.model_validate_json(input[0]) if input else GenerateEventScreenshotsInput()

    @workflow.run
    async def run(self, input: GenerateEventScreenshotsInput) -> None:
        """Generate screenshots for event definitions."""
        event_types = await workflow.execute_activity(
            load_event_types,
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(hours=3),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
        )

        result = await workflow.execute_activity(
            load_event_sessions,
            event_types,
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(hours=3),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
        )

        for event_type, event_session in result.event_sessions:
            screenshot_result = await workflow.execute_activity(
                take_event_screenshot,
                TakeEventScreenshotInput(
                    event_type=event_type,
                    event_session=event_session,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                schedule_to_close_timeout=timedelta(hours=3),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=2,
                    initial_interval=timedelta(minutes=1),
                ),
            )

            await workflow.execute_activity(
                store_event_screenshot,
                screenshot_result,
                start_to_close_timeout=timedelta(minutes=5),
                schedule_to_close_timeout=timedelta(hours=3),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=2,
                    initial_interval=timedelta(minutes=1),
                ),
            )
