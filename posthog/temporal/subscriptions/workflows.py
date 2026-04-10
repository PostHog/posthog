import json
import asyncio
import datetime as dt

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.event_usage import EventSource
from posthog.slo.types import SloArea, SloConfig, SloOperation, SloOutcome
from posthog.tasks.exports.failure_handler import is_user_query_error_type
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.exports.activities import export_asset_activity
from posthog.temporal.exports.retry_policy import EXPORT_RETRY_POLICY
from posthog.temporal.exports.types import (
    ExportAssetActivityInputs,
    ExportAssetResult,
    ExportError,
    extract_error_details,
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
    SubscriptionInfo,
    SubscriptionTriggerType,
    TrackedSubscriptionInputs,
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
            outcome_assets.append(
                ExportAssetResult(
                    exported_asset_id=asset_id,
                    success=False,
                    error=extract_error_details(result),
                )
            )
        else:
            outcome_assets.append(result)
            if result.success:
                successful_asset_ids.append(result.exported_asset_id)
    return outcome_assets, successful_asset_ids


@temporalio.workflow.defn(name="schedule-all-subscriptions")
class ScheduleAllSubscriptionsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ScheduleAllSubscriptionsWorkflowInputs:
        if not inputs:
            return ScheduleAllSubscriptionsWorkflowInputs()

        loaded = json.loads(inputs[0])
        return ScheduleAllSubscriptionsWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ScheduleAllSubscriptionsWorkflowInputs) -> None:
        fetch_inputs = FetchDueSubscriptionsActivityInputs(buffer_minutes=inputs.buffer_minutes)
        subscription_infos: list[SubscriptionInfo] = await temporalio.workflow.execute_activity(
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
        # Deterministic ID (no run_id suffix) prevents duplicate deliveries when
        # schedule runs overlap: Temporal guarantees no two open workflows can
        # share the same ID, so a still-running child rejects the duplicate start.
        tasks = []
        for sub in subscription_infos:
            task = temporalio.workflow.execute_child_workflow(
                ProcessSubscriptionWorkflow.run,
                TrackedSubscriptionInputs(
                    subscription_id=sub.subscription_id,
                    team_id=sub.team_id,
                    distinct_id=sub.distinct_id,
                    trigger_type=SubscriptionTriggerType.SCHEDULED,
                    slo=SloConfig(
                        operation=SloOperation.SUBSCRIPTION_DELIVERY,
                        area=SloArea.ANALYTIC_PLATFORM,
                        team_id=sub.team_id,
                        resource_id=str(sub.subscription_id),
                        distinct_id=sub.distinct_id,
                    ),
                ),
                id=f"process-subscription-{sub.subscription_id}",
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                execution_timeout=dt.timedelta(hours=2),
            )
            tasks.append(task)

        if tasks:
            # return_exceptions=True: individual subscription failures are isolated —
            # one failing subscription should not prevent others from being delivered.
            results = await asyncio.gather(*tasks, return_exceptions=True)
            failed_ids = []
            for sub, result in zip(subscription_infos, results):
                if isinstance(result, BaseException):
                    if isinstance(result, WorkflowAlreadyStartedError):
                        # A previous schedule run's child is still processing this
                        # subscription — not a failure, just skip it.
                        temporalio.workflow.logger.info(
                            "process_subscription.already_running",
                            extra={"subscription_id": sub.subscription_id},
                        )
                    else:
                        failed_ids.append(sub.subscription_id)
                        temporalio.workflow.logger.warning(
                            "process_subscription.child_workflow_error",
                            extra={"subscription_id": sub.subscription_id, "error": str(result)},
                        )

            if failed_ids:
                raise ApplicationError(
                    f"Subscription deliveries failed for IDs: {failed_ids}",
                    non_retryable=True,
                )


@temporalio.workflow.defn(name="process-subscription")
class ProcessSubscriptionWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> TrackedSubscriptionInputs:
        loaded = json.loads(inputs[0])
        return TrackedSubscriptionInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: TrackedSubscriptionInputs) -> None:
        assets_with_content = 0
        total_assets = 0
        asset_errors: list[ExportError] = []
        caught_error: BaseException | None = None

        try:
            # Phase 1: Prepare — create ExportedAssets
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
            asset_errors = [a.error for a in outcome_assets if a.error]

            non_user_errors = [e for e in asset_errors if not is_user_query_error_type(e.exception_class)]
            if inputs.slo and non_user_errors:
                inputs.slo.outcome = SloOutcome.FAILURE
                distinct_classes = sorted({e.exception_class for e in non_user_errors})
                inputs.slo.completion_properties.setdefault("error_type", "PartialExportFailure")
                inputs.slo.completion_properties.setdefault(
                    "error_message",
                    f"{len(non_user_errors)} export(s) failed: {', '.join(distinct_classes)}",
                )

            # Phase 3: Deliver — send all assets including failed ones (they show
            # a "failed to generate" placeholder in the email/Slack message)
            delivery_asset_ids = prepare_result.exported_asset_ids

            # is_new is true for target change triggers, false for scheduled and manual sends
            is_new = inputs.trigger_type == SubscriptionTriggerType.TARGET_CHANGE

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
                    maximum_interval=dt.timedelta(minutes=5),
                    maximum_attempts=5,
                ),
            )

        except Exception as e:
            caught_error = e
            # Defer the re-raise until after the finally block — see note below.

        finally:
            # Advance schedule — always for scheduled deliveries, even on failure
            if inputs.trigger_type == SubscriptionTriggerType.SCHEDULED:
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

            # Enrich SLO event with per-insight detail (non-user errors only).
            if inputs.slo:
                inputs.slo.completion_properties.update(
                    {
                        "assets_with_content": assets_with_content,
                        "total_assets": total_assets,
                        "asset_errors": [
                            {"error_type": e.exception_class, "error_trace": e.error_trace}
                            for e in asset_errors
                            if not is_user_query_error_type(e.exception_class)
                        ],
                    }
                )

        # Re-raise after cleanup completes. We can't re-raise inside the except
        # block because Temporal's SDK blocks new activity scheduling in the
        # finally block while an exception is propagating.
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
        tracked = TrackedSubscriptionInputs(
            subscription_id=inputs.subscription_id,
            team_id=inputs.team_id,
            distinct_id=inputs.distinct_id,
            previous_value=inputs.previous_value,
            invite_message=inputs.invite_message,
            trigger_type=inputs.trigger_type,
            slo=SloConfig(
                operation=SloOperation.SUBSCRIPTION_DELIVERY,
                area=SloArea.ANALYTIC_PLATFORM,
                team_id=inputs.team_id,
                resource_id=str(inputs.subscription_id),
                distinct_id=inputs.distinct_id,
            ),
        )
        child_id = f"process-subscription-{inputs.trigger_type}-{inputs.subscription_id}"
        await temporalio.workflow.execute_child_workflow(
            ProcessSubscriptionWorkflow.run,
            tracked,
            id=child_id,
            parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
            execution_timeout=dt.timedelta(hours=2),
        )
