import json
import typing
import asyncio
import datetime as dt
import dataclasses

from django.conf import settings

import temporalio.common
import temporalio.activity
import temporalio.workflow
from structlog import get_logger

from posthog.models.subscription import Subscription
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater

from ee.tasks.subscriptions import deliver_subscription_report_async

LOGGER = get_logger(__name__)

# Changed 20260109-01


@dataclasses.dataclass
class FetchDueSubscriptionsActivityInputs:
    """Inputs for `fetch_due_subscriptions_activity`."""

    buffer_minutes: int = 15

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "buffer_minutes": self.buffer_minutes,
        }


@temporalio.activity.defn
async def fetch_due_subscriptions_activity(inputs: FetchDueSubscriptionsActivityInputs) -> list[int]:
    """Return a list of subscription IDs that are due for delivery."""
    logger = LOGGER.bind()
    await logger.ainfo("Starting subscription fetch activity")

    now_with_buffer = dt.datetime.utcnow() + dt.timedelta(minutes=inputs.buffer_minutes)
    await logger.ainfo(f"Looking for subscriptions due before {now_with_buffer}")

    @database_sync_to_async(thread_sensitive=False)
    def get_subscription_ids() -> list[int]:
        return list(
            Subscription.objects.filter(next_delivery_date__lte=now_with_buffer, deleted=False)
            .exclude(dashboard__deleted=True)
            .exclude(insight__deleted=True)
            .values_list("id", flat=True)
        )

    await logger.ainfo("Starting database query for subscriptions")
    subscription_ids = await get_subscription_ids()
    await logger.ainfo(f"Database query completed, found {len(subscription_ids)} subscriptions")

    return subscription_ids


@dataclasses.dataclass
class DeliverSubscriptionReportActivityInputs:
    """Inputs for the `deliver_subscription_report_activity`."""

    subscription_id: int
    previous_value: typing.Optional[str] = None
    invite_message: typing.Optional[str] = None

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "subscription_id": self.subscription_id,
            "has_previous_value": self.previous_value is not None,
            "has_invite_message": self.invite_message is not None,
        }


@temporalio.activity.defn
async def deliver_subscription_report_activity(inputs: DeliverSubscriptionReportActivityInputs) -> None:
    """Deliver a subscription report."""
    async with Heartbeater():
        LOGGER.ainfo(
            "Delivering subscription report",
            subscription_id=inputs.subscription_id,
        )

        await deliver_subscription_report_async(
            subscription_id=inputs.subscription_id,
            previous_value=inputs.previous_value,
            invite_message=inputs.invite_message,
        )


@dataclasses.dataclass
class ScheduleAllSubscriptionsWorkflowInputs:
    """Inputs for the `ScheduleAllSubscriptionsWorkflow`."""

    buffer_minutes: int = 15

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "buffer_minutes": self.buffer_minutes,
        }


@temporalio.workflow.defn(name="schedule-all-subscriptions")
class ScheduleAllSubscriptionsWorkflow(PostHogWorkflow):
    """Workflow to schedule all subscriptions that are due for delivery."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ScheduleAllSubscriptionsWorkflowInputs:
        if not inputs:
            return ScheduleAllSubscriptionsWorkflowInputs()

        loaded = json.loads(inputs[0])
        return ScheduleAllSubscriptionsWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ScheduleAllSubscriptionsWorkflowInputs) -> None:
        """Run the workflow to schedule all subscriptions."""

        # Fetch subscription IDs that are due
        fetch_inputs = FetchDueSubscriptionsActivityInputs(buffer_minutes=inputs.buffer_minutes)
        subscription_ids: list[int] = await temporalio.workflow.execute_activity(
            fetch_due_subscriptions_activity,
            fetch_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(minutes=5),
                maximum_attempts=3,
                non_retryable_error_types=[],
            ),
        )

        # Fan-out delivery activities in parallel
        tasks = []
        for sub_id in subscription_ids:
            task = temporalio.workflow.execute_activity(
                deliver_subscription_report_activity,
                DeliverSubscriptionReportActivityInputs(subscription_id=sub_id),
                start_to_close_timeout=dt.timedelta(minutes=settings.TEMPORAL_TASK_TIMEOUT_MINUTES),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=5),
                    maximum_attempts=3,
                    non_retryable_error_types=[],
                ),
            )
            tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks)


@temporalio.workflow.defn(name="handle-subscription-value-change")
class HandleSubscriptionValueChangeWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> DeliverSubscriptionReportActivityInputs:
        loaded = json.loads(inputs[0])
        return DeliverSubscriptionReportActivityInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: DeliverSubscriptionReportActivityInputs) -> None:
        await temporalio.workflow.execute_activity(
            deliver_subscription_report_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=settings.TEMPORAL_TASK_TIMEOUT_MINUTES),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=5),
                maximum_interval=dt.timedelta(minutes=2),
                maximum_attempts=3,
            ),
        )
