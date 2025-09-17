import json
import datetime as dt
import dataclasses
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.product_analytics.upgrade_queries_activities import (
    GetInsightsToMigrateActivityInputs,
    MigrateInsightsBatchActivityInputs,
    get_insights_to_migrate,
    migrate_insights_batch,
)


@dataclasses.dataclass
class WorkflowState:
    after_id: Optional[int]
    migrated: int
    pages_done: int
    failed_ids: list[int]


@dataclasses.dataclass(frozen=True)
class UpgradeQueriesWorkflowInputs:
    """Inputs for the upgrade queries workflow."""

    batch_size: int = dataclasses.field(default=100)
    state: Optional[WorkflowState] = None
    test_continue_as_new: Optional[bool] = None


@workflow.defn(name="upgrade-queries")
class UpgradeQueriesWorkflow(PostHogWorkflow):
    @workflow.init
    def __init__(self, input: UpgradeQueriesWorkflowInputs) -> None:
        if input.state:
            self.state = input.state
        else:
            self.state = WorkflowState(after_id=None, migrated=0, pages_done=0, failed_ids=[])

        if input.test_continue_as_new:
            self.max_history_length: Optional[int] = 120
        else:
            self.max_history_length = None

    @staticmethod
    def parse_inputs(inputs: list[str]) -> UpgradeQueriesWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return UpgradeQueriesWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: UpgradeQueriesWorkflowInputs) -> None:
        while True:
            page = await workflow.execute_activity(
                get_insights_to_migrate,
                GetInsightsToMigrateActivityInputs(batch_size=inputs.batch_size, after_id=self.state.after_id),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(minutes=5),
                    maximum_interval=dt.timedelta(minutes=60),
                    maximum_attempts=3,
                ),
            )

            if not page.insight_ids:
                return  # finished

            failed = await workflow.execute_activity(
                migrate_insights_batch,
                MigrateInsightsBatchActivityInputs(insight_ids=page.insight_ids),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(minutes=10),
                    maximum_interval=dt.timedelta(minutes=60),
                    maximum_attempts=3,
                ),
            )

            self.state.failed_ids.extend(failed)
            self.state.after_id = page.last_id
            self.state.migrated += len(page.insight_ids)
            self.state.pages_done += 1

            # we might hit the event history limit, so check if we need to continue as new
            # https://docs.temporal.io/workflow-execution/event#event-history
            if self.should_continue_as_new():
                await workflow.wait_condition(lambda: workflow.all_handlers_finished())
                workflow.logger.info("Continuing as new")
                workflow.continue_as_new(UpgradeQueriesWorkflowInputs(state=self.state))

    def should_continue_as_new(self) -> bool:
        if workflow.info().is_continue_as_new_suggested():
            return True

        # This is just for ease-of-testing.  In production, we trust temporal to tell us when to continue as new.
        if self.max_history_length and workflow.info().get_current_history_length() > self.max_history_length:
            return True
        return False
