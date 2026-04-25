import json
import uuid
import typing
import asyncio
import datetime as dt

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ActivityError, ApplicationError, WorkflowAlreadyStartedError

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
    create_delivery_record,
    create_export_assets,
    deliver_subscription,
    fetch_due_subscriptions_activity,
    update_delivery_record,
)
from posthog.temporal.subscriptions.snapshot_activities import snapshot_subscription_insights
from posthog.temporal.subscriptions.types import (
    CreateDeliveryRecordInputs,
    CreateExportAssetsInputs,
    CreateExportAssetsResult,
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    DeliveryStatus,
    FetchDueSubscriptionsActivityInputs,
    ProcessSubscriptionWorkflowInputs,
    ScheduleAllSubscriptionsWorkflowInputs,
    SnapshotInsightsInputs,
    SubscriptionInfo,
    SubscriptionTriggerType,
    TrackedSubscriptionInputs,
    UpdateDeliveryRecordInputs,
)

# Rolling-deploy deprecation bundle (TODO slug: subscriptions-patched-cleanup)
# ---------------------------------------------------------------------------
# The items below exist ONLY to keep pre-rollout workflows replayable on new
# workers during a rolling deploy. They must be removed together, in two
# follow-up PRs, once the subscriptions task queue has drained past the oldest
# in-flight pre-patch workflow (workflow execution_timeout is 2h; wait ≥24h
# after deploy to be safe).
#
# Grep for `subscriptions-patched-cleanup` to find every site. The removal
# sequence matters — deleting `patched()` directly breaks replay of any
# workflow whose history already recorded the marker:
#   1. First cleanup PR: replace `workflow.patched(...)` with
#      `workflow.deprecate_patch(...)` (same runtime behavior; records a
#      "deprecated" marker instead).
#   2. Second cleanup PR (after another full drain): delete
#      `_reissue_phase_2_5_update_for_replay`, `_PATCH_ID_CONTENT_SNAPSHOT_DIRECT_WRITE`,
#      `CreateExportAssetsResult.insight_snapshots`, and
#      `UpdateDeliveryRecordInputs.content_snapshot`.
_PATCH_ID_CONTENT_SNAPSHOT_DIRECT_WRITE = "subscriptions-content-snapshot-direct-write"


async def _reissue_phase_2_5_update_for_replay(
    *,
    delivery_id: uuid.UUID,
    prepare_result: CreateExportAssetsResult,
    delivery_exported_asset_ids: list[int],
    subscription_id: int,
) -> None:
    """DO NOT MODIFY — must match the pre-rollout command shape exactly.

    Re-issues the old Phase 2.5 `update_delivery_record` command so pre-rollout
    workflows replay deterministically on new workers. Any change to the
    command's activity name, input type, or issued-or-not decision breaks
    replay for every in-flight pre-patch workflow and leaves them stuck.

    Correctness argument: the reconstructed content_snapshot only includes
    `insights` when the activity actually returned them (pre-patch history).
    When the new activity ran (insight_snapshots=None), it already persisted
    the snapshot to Postgres directly, so we omit that key to avoid the
    shallow-merge in `update_delivery_record` overwriting the in-activity
    write. `total_insight_count` is always included and always computed the
    same way on both code paths, so overwriting it is benign.

    Part of the `subscriptions-patched-cleanup` deprecation bundle — see the
    top-of-file comment for the two-step removal sequence.
    """
    legacy_content_snapshot: dict[str, typing.Any] = {
        "total_insight_count": prepare_result.total_insight_count,
    }
    if prepare_result.insight_snapshots is not None:
        legacy_content_snapshot["insights"] = prepare_result.insight_snapshots

    try:
        await temporalio.workflow.execute_activity(
            update_delivery_record,
            UpdateDeliveryRecordInputs(
                delivery_id=delivery_id,
                status=DeliveryStatus.STARTING,
                exported_asset_ids=delivery_exported_asset_ids or None,
                content_snapshot=legacy_content_snapshot,
            ),
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=5),
                maximum_interval=dt.timedelta(seconds=30),
                maximum_attempts=3,
            ),
        )
    except Exception:
        temporalio.workflow.logger.warning(
            "process_subscription.content_snapshot_persist_failed",
            extra={"subscription_id": subscription_id},
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
                    scheduled_at=sub.next_delivery_date,
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

        # Delivery record tracking
        delivery_id: uuid.UUID | None = None
        final_status = DeliveryStatus.SKIPPED
        delivery_exported_asset_ids: list[int] = []
        delivery_recipient_results: list[dict] = []
        # Hoisted so the finally block can always pass it to update_delivery_record,
        # even on early returns (no-assets SKIPPED) or exceptions before the summary
        # activity runs.
        change_summary: str | None = None

        try:
            # Create delivery history record — uuid4() is deterministic across
            # activity retries (replay) but unique across workflow retries.
            delivery_id = await temporalio.workflow.execute_activity(
                create_delivery_record,
                CreateDeliveryRecordInputs(
                    subscription_id=inputs.subscription_id,
                    team_id=inputs.team_id,
                    trigger_type=inputs.trigger_type,
                    scheduled_at=inputs.scheduled_at,
                    temporal_workflow_id=temporalio.workflow.info().workflow_id,
                    idempotency_key=str(temporalio.workflow.uuid4()),
                ),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=5),
                    maximum_interval=dt.timedelta(minutes=1),
                    maximum_attempts=3,
                ),
            )

            # Phase 1: Prepare — create ExportedAssets and persist insight snapshots
            # onto SubscriptionDelivery.content_snapshot (written from within the
            # activity to avoid shipping multi-MB query_results across Temporal's
            # ~2 MiB payload boundary).
            #
            # Adding the new `delivery_id` input field is a safe, non-breaking
            # change per Temporal's schema evolution guidance — activity inputs
            # are not part of the workflow command state machine, so this does
            # not need a workflow.patched() gate (unlike the Phase 2.5 removal
            # below, which is a command-sequence change).
            prepare_result = await temporalio.workflow.execute_activity(
                create_export_assets,
                CreateExportAssetsInputs(
                    subscription_id=inputs.subscription_id,
                    previous_value=inputs.previous_value,
                    delivery_id=delivery_id,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=2),
                    maximum_attempts=3,
                ),
            )

            if not prepare_result.exported_asset_ids:
                # No assets to export — SKIPPED status, finalized in finally
                return

            delivery_exported_asset_ids = prepare_result.exported_asset_ids

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

            # Rolling-deploy compat: re-issue the old Phase 2.5 command for
            # in-flight pre-patch workflows so their replay stays deterministic.
            # Post-patch workflows skip this entirely — the content_snapshot is
            # already in Postgres via create_export_assets writing directly.
            # `patched()` returns False on replay of a pre-rollout workflow's
            # history (no marker recorded) and True on any workflow that first
            # ran on new code. Inverted from the canonical pattern: we only
            # execute the legacy replay on the False branch.
            if not temporalio.workflow.patched(_PATCH_ID_CONTENT_SNAPSHOT_DIRECT_WRITE):
                if delivery_id is not None:
                    await _reissue_phase_2_5_update_for_replay(
                        delivery_id=delivery_id,
                        prepare_result=prepare_result,
                        delivery_exported_asset_ids=delivery_exported_asset_ids,
                        subscription_id=inputs.subscription_id,
                    )

            # Generate LLM change summary (best-effort, skip if not enabled).
            # Reads content_snapshot back from Postgres — it was persisted
            # inline by create_export_assets above, or by the legacy-replay
            # helper on pre-patch workflows.
            if delivery_id is not None:
                try:
                    snapshot_result = await temporalio.workflow.execute_activity(
                        snapshot_subscription_insights,
                        SnapshotInsightsInputs(
                            subscription_id=inputs.subscription_id,
                            team_id=inputs.team_id,
                            delivery_id=str(delivery_id),
                            exported_asset_ids=list(successful_asset_ids),
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=2),
                        heartbeat_timeout=dt.timedelta(seconds=60),
                        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                    )
                    change_summary = snapshot_result.summary_text
                except Exception:
                    temporalio.workflow.logger.warning(
                        "process_subscription.snapshot_failed",
                        extra={"subscription_id": inputs.subscription_id},
                    )

            # Phase 3: Deliver — send all assets including failed ones (they show
            # a "failed to generate" placeholder in the email/Slack message)
            delivery_asset_ids = prepare_result.exported_asset_ids

            # is_new is true for target change triggers, false for scheduled and manual sends
            is_new = inputs.trigger_type == SubscriptionTriggerType.TARGET_CHANGE

            deliver_result: DeliverSubscriptionResult = await temporalio.workflow.execute_activity(
                deliver_subscription,
                DeliverSubscriptionInputs(
                    subscription_id=inputs.subscription_id,
                    exported_asset_ids=delivery_asset_ids,
                    total_insight_count=prepare_result.total_insight_count,
                    is_new_subscription_target=is_new,
                    previous_value=inputs.previous_value,
                    invite_message=inputs.invite_message,
                    change_summary=change_summary,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=5),
                    maximum_attempts=5,
                ),
            )

            # Capture per-recipient results for the delivery record
            delivery_recipient_results = [
                {
                    "recipient": r.recipient,
                    "status": r.status,
                    **({"error": r.error} if r.error else {}),
                }
                for r in deliver_result.recipient_results
            ]
            final_status = DeliveryStatus.COMPLETED

        except Exception as e:
            # Preserve recipient outcomes carried in non-retryable delivery errors
            # (e.g. Slack missing integration) so history isn't empty on failure.
            if isinstance(e, ActivityError) and isinstance(e.cause, ApplicationError):
                details = e.cause.details
                if details and isinstance(details[0], dict):
                    recipient_results = details[0].get("recipient_results")
                    if isinstance(recipient_results, list):
                        delivery_recipient_results = recipient_results
            caught_error = e
            final_status = DeliveryStatus.FAILED
            # Defer the re-raise until after the finally block — see note below.

        finally:
            # Finalize delivery record with whatever state we have
            if delivery_id is not None:
                try:
                    await temporalio.workflow.execute_activity(
                        update_delivery_record,
                        UpdateDeliveryRecordInputs(
                            delivery_id=delivery_id,
                            status=final_status,
                            exported_asset_ids=delivery_exported_asset_ids or None,
                            recipient_results=delivery_recipient_results or None,
                            change_summary=change_summary,
                            error={"message": str(caught_error)[:500], "type": type(caught_error).__name__}
                            if caught_error
                            else None,
                            finished=True,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=2),
                        retry_policy=temporalio.common.RetryPolicy(
                            initial_interval=dt.timedelta(seconds=5),
                            maximum_interval=dt.timedelta(minutes=1),
                            maximum_attempts=3,
                        ),
                    )
                except Exception:
                    temporalio.workflow.logger.exception(
                        "update_delivery_record failed (delivery history is best-effort when a prior error exists)"
                    )
                    if caught_error is None:
                        raise

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
