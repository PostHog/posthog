import json
import typing
import asyncio
import datetime as dt
import traceback

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ApplicationError

from posthog.event_usage import EventSource
from posthog.slo.types import SloOutcome
from posthog.tasks.exports.failure_handler import is_user_query_error_type
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.exports.activities import emit_delivery_outcome, emit_delivery_started, export_asset_activity
from posthog.temporal.exports.retry_policy import EXPORT_RETRY_POLICY
from posthog.temporal.exports.types import (
    EmitDeliveryOutcomeInput,
    ExportAssetActivityInputs,
    ExportAssetResult,
    ExportError,
)
from posthog.temporal.subscriptions.activities import (
    advance_next_delivery_date,
    create_export_assets,
    deliver_subscription,
    fetch_due_subscriptions_activity,
)
from posthog.temporal.subscriptions.types import (
    CreateExportAssetsInputs,
    DeliverSubscriptionInputs,
    FetchDueSubscriptionsActivityInputs,
    ProcessSubscriptionWorkflowInputs,
    ScheduleAllSubscriptionsWorkflowInputs,
)

from ee.tasks.subscriptions import get_subscription_failure_metric


class ExportErrorDetails(typing.NamedTuple):
    """Failure metadata extracted from a Temporal activity exception.

    Fields mirror the ApplicationError details emitted by export_asset_activity:
    [exception_class, duration_ms, export_format, attempt, error_trace].
    """

    exception_class: str | None = None
    duration_ms: float | None = None
    export_format: str = ""
    attempts: int = 1
    error_trace: str | None = None


def _extract_error_details(exc: BaseException) -> ExportErrorDetails:
    """Extract failure metadata from a Temporal activity exception chain.

    asyncio.gather(return_exceptions=True) yields BaseException, but Temporal
    wraps activity failures as ActivityError → ApplicationError. We narrow
    through that chain to reach the structured details.
    """
    from temporalio.exceptions import ActivityError, ApplicationError

    if not isinstance(exc, ActivityError) or not isinstance(exc.cause, ApplicationError):
        return ExportErrorDetails()

    details = exc.cause.details
    return ExportErrorDetails(
        exception_class=details[0] if len(details) >= 1 and isinstance(details[0], str) else None,
        duration_ms=details[1] if len(details) >= 2 and isinstance(details[1], (int, float)) else None,
        export_format=details[2] if len(details) >= 3 and isinstance(details[2], str) else "",
        attempts=details[3] if len(details) >= 4 and isinstance(details[3], int) else 1,
        error_trace=details[4] if len(details) >= 5 and isinstance(details[4], str) else None,
    )


def _build_outcome_assets(
    asset_ids: list[int],
    export_results: list[ExportAssetResult | BaseException],
) -> tuple[list[ExportAssetResult], list[int]]:
    """Classify export results into outcome assets and collect successful asset IDs.

    BaseException objects from asyncio.gather(return_exceptions=True) aren't
    serializable across the Temporal activity boundary, so this classification
    must happen in the workflow, not in an activity.
    """
    outcome_assets: list[ExportAssetResult] = []
    successful_asset_ids: list[int] = []
    for asset_id, result in zip(asset_ids, export_results):
        if isinstance(result, BaseException):
            err = _extract_error_details(result)
            outcome_assets.append(
                ExportAssetResult(
                    exported_asset_id=asset_id,
                    success=False,
                    exception_class=err.exception_class,
                    error_trace=err.error_trace,
                    duration_ms=err.duration_ms,
                    export_format=err.export_format,
                    attempts=err.attempts,
                )
            )
        else:
            outcome_assets.append(result)
            if result.success:
                successful_asset_ids.append(result.exported_asset_id)
    return outcome_assets, successful_asset_ids


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

        # Fan-out child workflows — one per subscription, fully isolated.
        # Idempotent ID (no run_id suffix) prevents duplicate deliveries when
        # schedule runs overlap: if the previous run's child is still executing,
        # Temporal rejects the duplicate start and we log it below.
        tasks = []
        for sub_id in subscription_ids:
            task = temporalio.workflow.execute_child_workflow(
                ProcessSubscriptionWorkflow.run,
                ProcessSubscriptionWorkflowInputs(subscription_id=sub_id),
                id=f"process-subscription-{sub_id}",
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                execution_timeout=dt.timedelta(hours=2),
            )
            tasks.append(task)

        if tasks:
            # return_exceptions=True: individual subscription failures are isolated —
            # one failing subscription should not prevent others from being delivered.
            results = await asyncio.gather(*tasks, return_exceptions=True)
            failed_ids = []
            for sub_id, result in zip(subscription_ids, results):
                if isinstance(result, BaseException):
                    failed_ids.append(sub_id)
                    temporalio.workflow.logger.warning(
                        "process_subscription.child_workflow_error",
                        extra={"subscription_id": sub_id, "error": str(result)},
                    )

            if failed_ids:
                raise ApplicationError(
                    f"Subscription deliveries failed for IDs: {failed_ids}",
                    non_retryable=True,
                )


@temporalio.workflow.defn(name="process-subscription")
class ProcessSubscriptionWorkflow(PostHogWorkflow):
    """Child workflow that handles a single subscription: prepare -> export -> deliver -> emit."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ProcessSubscriptionWorkflowInputs:
        loaded = json.loads(inputs[0])
        return ProcessSubscriptionWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ProcessSubscriptionWorkflowInputs) -> None:
        start_time = temporalio.workflow.time()
        delivery_outcome = SloOutcome.SUCCESS
        assets_with_content = 0
        total_assets = 0
        errors: list[ExportError] = []
        prepare_result = None
        caught_error: BaseException | None = None

        try:
            # SLO started — workflow owns the lifecycle, fires before any work
            await temporalio.workflow.execute_activity(
                emit_delivery_started,
                inputs.subscription_id,
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=5),
                    maximum_interval=dt.timedelta(minutes=1),
                    maximum_attempts=3,
                ),
            )

            # Phase 1: Prepare — create ExportedAssets
            # previous_value is passed so the activity can skip asset creation if the
            # target value hasn't changed
            prepare_result = await temporalio.workflow.execute_activity(
                create_export_assets,
                CreateExportAssetsInputs(
                    subscription_id=inputs.subscription_id,
                    previous_value=inputs.previous_value,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=2),
                    maximum_attempts=3,
                ),
            )

            if not prepare_result.exported_asset_ids:
                return

            # Phase 2: Fan-out export — one activity per insight, independent retry
            export_tasks = []
            for asset_id in prepare_result.exported_asset_ids:
                task = temporalio.workflow.execute_activity(
                    export_asset_activity,
                    ExportAssetActivityInputs(
                        exported_asset_id=asset_id,
                        source=EventSource.SUBSCRIPTION,
                    ),
                    start_to_close_timeout=dt.timedelta(hours=1),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=EXPORT_RETRY_POLICY,
                )
                export_tasks.append((asset_id, task))

            # Gather results — continue on failure (partial success OK)
            export_results: list[ExportAssetResult | BaseException] = await asyncio.gather(
                *[task for _, task in export_tasks],
                return_exceptions=True,
            )

            # Classify export results
            asset_ids = [aid for aid, _ in export_tasks]
            outcome_assets, successful_asset_ids = _build_outcome_assets(asset_ids, export_results)
            assets_with_content = len(successful_asset_ids)
            total_assets = len(outcome_assets)
            errors = [
                ExportError(exception_class=a.exception_class or "", error_trace=a.error_trace or "")
                for a in outcome_assets
                if a.exception_class
            ]

            if assets_with_content < total_assets:
                delivery_outcome = SloOutcome.FAILURE
            # Only count system failures in the metric, not user query errors
            system_failures = [e for e in errors if not is_user_query_error_type(e.exception_class)]
            if system_failures:
                get_subscription_failure_metric(
                    prepare_result.target_type, "temporal", failure_type="asset_generation"
                ).add(1)

            # Phase 3: Deliver — send all assets including failed ones (they show
            # a "failed to generate" placeholder in the email/Slack message)
            delivery_asset_ids = prepare_result.exported_asset_ids

            # is_new is true when previous_value is set (target change), false for scheduled delivery
            is_new = inputs.previous_value is not None

            await temporalio.workflow.execute_activity(
                deliver_subscription,
                DeliverSubscriptionInputs(
                    subscription_id=inputs.subscription_id,
                    exported_asset_ids=delivery_asset_ids,
                    total_insight_count=prepare_result.total_insight_count,
                    is_new_subscription_target=is_new,
                    previous_value=inputs.previous_value,
                    invite_message=inputs.invite_message,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=2),
                    maximum_attempts=3,
                ),
            )

        except Exception as e:
            delivery_outcome = SloOutcome.FAILURE
            errors.append(
                ExportError(
                    exception_class=type(e).__name__,
                    error_trace="\n".join(traceback.format_exception(e)[:5]),
                )
            )
            caught_error = e
            # Don't re-raise — let finally run cleanup activities first

        finally:
            # Advance schedule — always for scheduled deliveries, even on failure.
            # This must not be gated on prepare_result or asset count, otherwise a
            # persistently broken subscription (e.g. deleted insight) stays "due"
            # forever and gets re-processed every schedule tick.
            if inputs.previous_value is None:
                await temporalio.workflow.execute_activity(
                    advance_next_delivery_date,
                    inputs.subscription_id,
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=temporalio.common.RetryPolicy(
                        initial_interval=dt.timedelta(seconds=5),
                        maximum_interval=dt.timedelta(minutes=1),
                        maximum_attempts=3,
                    ),
                )

            # SLO completed — fires last, after all side effects
            if prepare_result and prepare_result.team_id:
                duration_ms = (temporalio.workflow.time() - start_time) * 1000
                await temporalio.workflow.execute_activity(
                    emit_delivery_outcome,
                    EmitDeliveryOutcomeInput(
                        subscription_id=inputs.subscription_id,
                        team_id=prepare_result.team_id,
                        distinct_id=prepare_result.distinct_id,
                        outcome=delivery_outcome,
                        duration_ms=duration_ms,
                        assets_with_content=assets_with_content,
                        total_assets=total_assets,
                        errors=errors,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=temporalio.common.RetryPolicy(
                        initial_interval=dt.timedelta(seconds=5),
                        maximum_interval=dt.timedelta(minutes=1),
                        maximum_attempts=3,
                    ),
                )

        # Re-raise after cleanup completes
        if caught_error:
            raise caught_error


@temporalio.workflow.defn(name="handle-subscription-value-change")
class HandleSubscriptionValueChangeWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ProcessSubscriptionWorkflowInputs:
        loaded = json.loads(inputs[0])
        return ProcessSubscriptionWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ProcessSubscriptionWorkflowInputs) -> None:
        await temporalio.workflow.execute_child_workflow(
            ProcessSubscriptionWorkflow.run,
            inputs,
            id=f"process-subscription-change-{inputs.subscription_id}",
            parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
            execution_timeout=dt.timedelta(hours=2),
        )
