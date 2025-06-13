import asyncio
import dataclasses
import datetime as dt
import typing
from datetime import datetime, timedelta

import structlog
import temporalio.activity
import temporalio.common
import temporalio.workflow
from django.conf import settings

from posthog.models.subscription import Subscription
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_internal_logger

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class ScheduleSubscriptionsActivityInputs:
    """Inputs for the `schedule_subscriptions_activity`."""

    buffer_minutes: int = 15

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "buffer_minutes": self.buffer_minutes,
        }


@temporalio.activity.defn
async def schedule_subscriptions_activity(inputs: ScheduleSubscriptionsActivityInputs) -> None:
    """Schedule all subscriptions that are due for delivery."""
    async with Heartbeater():
        logger = get_internal_logger()

        # This is similar to the Celery implementation but adapted for async
        now_with_buffer = datetime.utcnow() + timedelta(minutes=inputs.buffer_minutes)

        # We need to use sync_to_async for Django ORM operations in async context
        from asgiref.sync import sync_to_async

        # Get all subscriptions that need to be delivered
        @sync_to_async
        def get_subscriptions():
            return list(
                Subscription.objects.filter(next_delivery_date__lte=now_with_buffer, deleted=False)
                .exclude(dashboard__deleted=True)
                .exclude(insight__deleted=True)
                .all()
            )

        subscriptions = await get_subscriptions()

        await logger.ainfo(
            "Processing subscriptions in parallel",
            subscription_count=len(subscriptions),
        )

        # Create a list of tasks to execute in parallel
        tasks = []

        for subscription in subscriptions:
            await logger.ainfo(
                "Scheduling subscription",
                subscription_id=subscription.id,
                next_delivery_date=subscription.next_delivery_date,
                destination=subscription.target_type,
            )

            # Create a task for each subscription but don't await it yet
            task = temporalio.workflow.execute_activity(
                deliver_subscription_report_activity,
                DeliverSubscriptionReportActivityInputs(subscription_id=subscription.id),
                start_to_close_timeout=dt.timedelta(
                    seconds=settings.PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES * 60 * 1.5
                ),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=5),
                    maximum_attempts=3,
                    non_retryable_error_types=[],
                ),
            )
            tasks.append(task)

        # Execute all tasks in parallel and wait for all to complete
        if tasks:
            await asyncio.gather(*tasks)


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
        logger = get_internal_logger()

        # We need to use sync_to_async for Django ORM operations in async context
        from asgiref.sync import sync_to_async

        # Import the original function to reuse the logic
        from ee.tasks.subscriptions import _deliver_subscription_report

        # Wrap the synchronous function to be called in async context
        deliver_subscription = sync_to_async(_deliver_subscription_report)

        await logger.ainfo(
            "Delivering subscription report",
            subscription_id=inputs.subscription_id,
        )

        # Call the original implementation
        await deliver_subscription(
            subscription_id=inputs.subscription_id,
            previous_value=inputs.previous_value,
            invite_message=inputs.invite_message,
        )


@dataclasses.dataclass
class HandleSubscriptionValueChangeActivityInputs:
    """Inputs for the `handle_subscription_value_change_activity`."""

    subscription_id: int
    previous_value: str
    invite_message: typing.Optional[str] = None

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "subscription_id": self.subscription_id,
            "has_invite_message": self.invite_message is not None,
        }


@temporalio.activity.defn
async def handle_subscription_value_change_activity(inputs: HandleSubscriptionValueChangeActivityInputs) -> None:
    """Handle a change in subscription value."""
    async with Heartbeater():
        logger = get_internal_logger()

        # We need to use sync_to_async for Django ORM operations in async context
        from asgiref.sync import sync_to_async

        # Import the original function to reuse the logic
        from ee.tasks.subscriptions import _deliver_subscription_report

        # Wrap the synchronous function to be called in async context
        deliver_subscription = sync_to_async(_deliver_subscription_report)

        await logger.ainfo(
            "Handling subscription value change",
            subscription_id=inputs.subscription_id,
        )

        # Call the original implementation
        await deliver_subscription(
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
        """Parse inputs from the management command CLI."""
        import json

        if not inputs:
            return ScheduleAllSubscriptionsWorkflowInputs()

        loaded = json.loads(inputs[0])
        return ScheduleAllSubscriptionsWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ScheduleAllSubscriptionsWorkflowInputs) -> None:
        """Run the workflow to schedule all subscriptions."""
        schedule_subscriptions_inputs = ScheduleSubscriptionsActivityInputs(
            buffer_minutes=inputs.buffer_minutes,
        )

        await temporalio.workflow.execute_activity(
            schedule_subscriptions_activity,
            schedule_subscriptions_inputs,
            start_to_close_timeout=dt.timedelta(minutes=30),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(minutes=5),
                maximum_attempts=3,
                non_retryable_error_types=[],
            ),
        )
