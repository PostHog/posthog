import json
import typing
import asyncio
import datetime as dt
import dataclasses

from django.conf import settings

import posthoganalytics
import temporalio.common
import temporalio.activity
import temporalio.workflow
from structlog import get_logger
from temporalio.exceptions import ApplicationError

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
class EmitSubscriptionDeliveryStartedInputs:
    subscription_ids: list[int]


@temporalio.activity.defn
async def emit_subscription_delivery_started_activity(
    inputs: EmitSubscriptionDeliveryStartedInputs,
) -> None:
    @database_sync_to_async(thread_sensitive=False)
    def load_team_ids() -> dict[int, int]:
        return dict(Subscription.objects.filter(id__in=inputs.subscription_ids).values_list("id", "team_id"))

    sub_to_team = await load_team_ids()

    for sub_id in inputs.subscription_ids:
        team_id = sub_to_team.get(sub_id)
        if team_id is None:
            continue
        posthoganalytics.capture(
            distinct_id=str(team_id),
            event="subscription_delivery_started",
            properties={"subscription_id": sub_id, "team_id": team_id},
        )

    await asyncio.to_thread(posthoganalytics.flush)


@dataclasses.dataclass
class EmitSubscriptionDeliveryOutcomeInputs:
    succeeded_subscription_ids: list[int]
    failed_deliveries: list[dict[str, typing.Any]]


@temporalio.activity.defn
async def emit_subscription_delivery_outcome_events_activity(
    inputs: EmitSubscriptionDeliveryOutcomeInputs,
) -> None:
    all_sub_ids = inputs.succeeded_subscription_ids + [f["subscription_id"] for f in inputs.failed_deliveries]

    @database_sync_to_async(thread_sensitive=False)
    def load_team_ids() -> dict[int, int]:
        return dict(Subscription.objects.filter(id__in=all_sub_ids).values_list("id", "team_id"))

    sub_to_team = await load_team_ids()

    for sub_id in inputs.succeeded_subscription_ids:
        team_id = sub_to_team.get(sub_id)
        if team_id is None:
            continue
        posthoganalytics.capture(
            distinct_id=str(team_id),
            event="subscription_delivery_succeeded",
            properties={"subscription_id": sub_id, "team_id": team_id},
        )

    for failure in inputs.failed_deliveries:
        sub_id = failure["subscription_id"]
        team_id = sub_to_team.get(sub_id)
        if team_id is None:
            continue
        posthoganalytics.capture(
            distinct_id=str(team_id),
            event="subscription_delivery_exhausted",
            properties={
                "subscription_id": sub_id,
                "team_id": team_id,
                "error_type": failure.get("error_type", ""),
                "error_message": failure.get("error_message", ""),
            },
        )

    await asyncio.to_thread(posthoganalytics.flush)


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

        # Emit started events before delivery
        try:
            await temporalio.workflow.execute_activity(
                emit_subscription_delivery_started_activity,
                EmitSubscriptionDeliveryStartedInputs(subscription_ids=subscription_ids),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=5),
                    maximum_interval=dt.timedelta(minutes=1),
                    maximum_attempts=3,
                ),
            )
        except Exception as emit_error:
            temporalio.workflow.logger.error(
                "Failed to emit subscription delivery started events",
                extra={"error": str(emit_error)},
            )

        # Fan-out delivery activities in parallel
        tasks: list[tuple[int, typing.Coroutine[typing.Any, typing.Any, None]]] = []
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
            tasks.append((sub_id, task))

        if not tasks:
            return

        results = await asyncio.gather(*[t for _, t in tasks], return_exceptions=True)

        succeeded: list[int] = []
        failed: list[dict[str, typing.Any]] = []
        for (sub_id, _), result in zip(tasks, results):
            if isinstance(result, BaseException):
                failed.append(
                    {
                        "subscription_id": sub_id,
                        "error_type": type(result).__name__,
                        "error_message": str(result),
                    }
                )
            else:
                succeeded.append(sub_id)

        try:
            await temporalio.workflow.execute_activity(
                emit_subscription_delivery_outcome_events_activity,
                EmitSubscriptionDeliveryOutcomeInputs(
                    succeeded_subscription_ids=succeeded,
                    failed_deliveries=failed,
                ),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=5),
                    maximum_interval=dt.timedelta(minutes=1),
                    maximum_attempts=3,
                ),
            )
        except Exception as emit_error:
            temporalio.workflow.logger.error(
                "Failed to emit subscription delivery outcome events",
                extra={"error": str(emit_error)},
            )

        if failed:
            failed_ids = [f["subscription_id"] for f in failed]
            raise ApplicationError(f"Subscription deliveries failed for IDs: {failed_ids}", non_retryable=True)


@temporalio.workflow.defn(name="handle-subscription-value-change")
class HandleSubscriptionValueChangeWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> DeliverSubscriptionReportActivityInputs:
        loaded = json.loads(inputs[0])
        return DeliverSubscriptionReportActivityInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: DeliverSubscriptionReportActivityInputs) -> None:
        try:
            await temporalio.workflow.execute_activity(
                emit_subscription_delivery_started_activity,
                EmitSubscriptionDeliveryStartedInputs(subscription_ids=[inputs.subscription_id]),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=5),
                    maximum_interval=dt.timedelta(minutes=1),
                    maximum_attempts=3,
                ),
            )
        except Exception as emit_error:
            temporalio.workflow.logger.error(
                "Failed to emit subscription delivery started event",
                extra={"subscription_id": inputs.subscription_id, "error": str(emit_error)},
            )

        succeeded: list[int] = []
        failed: list[dict[str, typing.Any]] = []
        delivery_error: Exception | None = None

        try:
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
            succeeded.append(inputs.subscription_id)
        except Exception as e:
            delivery_error = e
            failed.append(
                {
                    "subscription_id": inputs.subscription_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                }
            )

        try:
            await temporalio.workflow.execute_activity(
                emit_subscription_delivery_outcome_events_activity,
                EmitSubscriptionDeliveryOutcomeInputs(
                    succeeded_subscription_ids=succeeded,
                    failed_deliveries=failed,
                ),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=5),
                    maximum_interval=dt.timedelta(minutes=1),
                    maximum_attempts=3,
                ),
            )
        except Exception as emit_error:
            temporalio.workflow.logger.error(
                "Failed to emit subscription delivery outcome event",
                extra={"subscription_id": inputs.subscription_id, "error": str(emit_error)},
            )

        if delivery_error is not None:
            raise delivery_error
