"""Workflows for backfilling materialized property columns.

Two workflows live here:

* ``BackfillMaterializedPropertyWorkflow`` — legacy per-slot workflow. Kept registered for
  backwards compatibility with already-running instances; the API no longer starts new ones.

* ``BackfillMaterializedPropertiesBatchWorkflow`` — the weekly batched workflow described in the
  dynamic property materialization RFC. It picks up all PENDING slots, assigns them column
  indexes, runs a single ``ALTER TABLE UPDATE`` with a ``multiIf`` per column, polls until the
  mutation completes on every shard, then transitions the slots to READY.
"""

import json
import datetime as dt
import dataclasses

import structlog
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.backfill_materialized_property.activities import (
    ActivateSlotsInputs,
    AssignPendingSlotsInputs,
    AssignPendingSlotsResult,
    BackfillMaterializedColumnInputs,
    ClearCompactionTargetsInputs,
    FailSlotsInputs,
    FinalizeCompactionInputs,
    RunBatchedMutationInputs,
    UpdateSlotStateInputs,
    activate_slots,
    assign_pending_slots,
    backfill_materialized_column,
    clear_compaction_targets,
    fail_slots,
    finalize_compaction,
    run_batched_mutation,
    update_slot_state,
)
from posthog.temporal.common.base import PostHogWorkflow


@dataclasses.dataclass
class BackfillMaterializedPropertyInputs:
    """Inputs for the backfill materialized property workflow."""

    team_id: int
    slot_id: str
    property_name: str
    mat_column_name: str
    # Wait time for ingestion cache refresh (default 180s, can be 0 for tests)
    cache_refresh_wait_seconds: int = 180
    # Retry interval for state updates (default 10s, can be shorter for tests)
    state_update_retry_interval_seconds: int = 10


@workflow.defn(name="backfill-materialized-property")
class BackfillMaterializedPropertyWorkflow(PostHogWorkflow):
    """
    Workflow to backfill a materialized property column.

    Flow:
    1. Wait 3 minutes for plugin-server ingestion cache to refresh
       (ensures no gap between backfill and future new events being materialized)
    2. Run ClickHouse ALTER TABLE UPDATE to backfill historical events
    3. Update slot state to READY (or ERROR if failed)
    """

    @classmethod
    def parse_inputs(cls, inputs: list[str]) -> BackfillMaterializedPropertyInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return BackfillMaterializedPropertyInputs(**loaded)

    @workflow.run
    async def run(self, inputs: BackfillMaterializedPropertyInputs) -> None:
        """Execute the backfill workflow."""
        logger = structlog.get_logger("backfill_materialized_property")

        try:
            # Wait for plugin-server TeamManager cache to refresh
            # IMPORTANT: plugin-server/src/utils/team-manager.ts has refreshAgeMs=2min + refreshJitterMs=30s
            # We wait 3 minutes to account for max refresh time (2.5min) + buffer
            # This prevents a gap where new events come in after backfill completes
            # but before the ingestion server knows about the new materialized column
            if inputs.cache_refresh_wait_seconds > 0:
                logger.info(
                    "Waiting for ingestion cache refresh",
                    team_id=inputs.team_id,
                    slot_id=inputs.slot_id,
                    wait_seconds=inputs.cache_refresh_wait_seconds,
                )
                await workflow.sleep(dt.timedelta(seconds=inputs.cache_refresh_wait_seconds))

            # Run backfill
            logger.info(
                "Starting backfill",
                team_id=inputs.team_id,
                property_name=inputs.property_name,
                mat_column_name=inputs.mat_column_name,
            )
            await workflow.execute_activity(
                backfill_materialized_column,
                BackfillMaterializedColumnInputs(
                    team_id=inputs.team_id,
                    property_name=inputs.property_name,
                    mat_column_name=inputs.mat_column_name,
                ),
                start_to_close_timeout=dt.timedelta(hours=2),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(minutes=1),
                    maximum_interval=dt.timedelta(minutes=10),
                    maximum_attempts=3,
                ),
            )

            # Update state to READY
            logger.info("Backfill complete, updating state to READY", slot_id=inputs.slot_id)
            await workflow.execute_activity(
                update_slot_state,
                UpdateSlotStateInputs(slot_id=inputs.slot_id, state="READY"),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=inputs.state_update_retry_interval_seconds),
                    maximum_interval=dt.timedelta(minutes=1),
                    maximum_attempts=5,  # State update is important, retry more
                ),
            )

            logger.info("Workflow completed successfully", slot_id=inputs.slot_id)

        except Exception as e:
            # Update state to ERROR
            logger.exception("Workflow failed", slot_id=inputs.slot_id)

            try:
                await workflow.execute_activity(
                    update_slot_state,
                    UpdateSlotStateInputs(
                        slot_id=inputs.slot_id,
                        state="ERROR",
                        error_message=str(e),
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=RetryPolicy(
                        initial_interval=dt.timedelta(seconds=inputs.state_update_retry_interval_seconds),
                        maximum_interval=dt.timedelta(minutes=1),
                        maximum_attempts=5,
                    ),
                )
            except Exception:
                logger.exception(
                    "Failed to update state to ERROR",
                    slot_id=inputs.slot_id,
                    original_error=str(e),
                )

            # Re-raise the original exception
            raise


@dataclasses.dataclass
class BackfillMaterializedPropertiesBatchInputs:
    """Inputs for the weekly batched dmat backfill workflow."""

    # Wait time between assigning slots and submitting the mutation, so plugin-server
    # TeamManager caches refresh and start populating the new columns for fresh events
    # before the historical backfill mutation runs. Default 180s — see the legacy workflow
    # for details. Tests can pass 0.
    cache_refresh_wait_seconds: int = 180


@workflow.defn(name="backfill-materialized-properties-batch")
class BackfillMaterializedPropertiesBatchWorkflow(PostHogWorkflow):
    """
    Weekly batched workflow that materializes all PENDING slots in one mutation.

    Flow:
      1. Atomically assign each PENDING slot to a free column index for its team and
         transition it to BACKFILL.
      2. Sleep ~3 minutes so the plugin-server ingestion cache picks up the new
         (slot_index, property) mappings before the historical backfill runs.
      3. Submit a single ALTER TABLE UPDATE with a multiIf branch per (column, team)
         and block until the mutation completes on every shard. The mutation is
         idempotent: re-runs of the same workflow attach to the existing mutation
         rather than enqueueing a duplicate.
      4. Transition the assigned slots to READY. HogQL immediately starts using the
         materialized columns once the slots are READY.

    On any failure between steps 1 and 4, the affected slots are transitioned to ERROR
    so an operator can investigate and reset them to PENDING for the next cycle.
    """

    @classmethod
    def parse_inputs(cls, inputs: list[str]) -> BackfillMaterializedPropertiesBatchInputs:
        loaded = json.loads(inputs[0]) if inputs else {}
        return BackfillMaterializedPropertiesBatchInputs(**loaded)

    @workflow.run
    async def run(self, inputs: BackfillMaterializedPropertiesBatchInputs) -> None:
        logger = structlog.get_logger("backfill_materialized_properties_batch")
        # Use the per-execution run_id rather than workflow_id. The schedule reuses the same
        # workflow_id every week, so workflow_id alone can't distinguish "this firing's commits"
        # from "last week's firing's commits". run_id is unique per execution and stays constant
        # across activity retries — exactly what we need to make `assign_pending_slots` idempotent
        # against an activity retry that hits a partially-committed PENDING→BACKFILL transition.
        workflow_run_id = workflow.info().workflow_run_id

        assignment: AssignPendingSlotsResult = await workflow.execute_activity(
            assign_pending_slots,
            AssignPendingSlotsInputs(workflow_id=workflow_run_id),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(minutes=1),
                maximum_attempts=3,
            ),
        )

        if not assignment.assigned_slot_ids and not assignment.compacted_slot_ids:
            logger.info("Nothing to do — no PENDING slots and no compaction needed", workflow_run_id=workflow_run_id)
            return

        if inputs.cache_refresh_wait_seconds > 0:
            logger.info(
                "Waiting for ingestion cache refresh",
                wait_seconds=inputs.cache_refresh_wait_seconds,
                pending_count=len(assignment.assigned_slot_ids),
                compacted_count=len(assignment.compacted_slot_ids),
            )
            await workflow.sleep(dt.timedelta(seconds=inputs.cache_refresh_wait_seconds))

        if assignment.assignments:
            try:
                await workflow.execute_activity(
                    run_batched_mutation,
                    RunBatchedMutationInputs(assignments=assignment.assignments),
                    # Mutations on sharded_events can run for hours at production scale. The
                    # activity polls system.mutations rather than blocking on a single client
                    # connection, so this timeout bounds wall-clock duration, not connection life.
                    start_to_close_timeout=dt.timedelta(hours=12),
                    heartbeat_timeout=dt.timedelta(minutes=5),
                    retry_policy=RetryPolicy(
                        initial_interval=dt.timedelta(minutes=2),
                        maximum_interval=dt.timedelta(minutes=10),
                        maximum_attempts=3,
                    ),
                )
            except Exception as e:
                logger.exception(
                    "Batched mutation failed; rolling back slot transitions", workflow_run_id=workflow_run_id
                )
                try:
                    # PENDING slots that were promoted to BACKFILL get marked ERROR so an operator
                    # can retry them. Compacted slots stay READY — their old column still has
                    # correct data — but we clear `compaction_target_slot_index` so the cancelled
                    # column is freed and the next workflow run picks fresh targets.
                    if assignment.assigned_slot_ids:
                        await workflow.execute_activity(
                            fail_slots,
                            FailSlotsInputs(
                                slot_ids=assignment.assigned_slot_ids,
                                error_message=str(e),
                            ),
                            start_to_close_timeout=dt.timedelta(minutes=5),
                            retry_policy=RetryPolicy(
                                initial_interval=dt.timedelta(seconds=10),
                                maximum_interval=dt.timedelta(minutes=1),
                                maximum_attempts=5,
                            ),
                        )
                    if assignment.compacted_slot_ids:
                        await workflow.execute_activity(
                            clear_compaction_targets,
                            ClearCompactionTargetsInputs(slot_ids=assignment.compacted_slot_ids),
                            start_to_close_timeout=dt.timedelta(minutes=5),
                            retry_policy=RetryPolicy(
                                initial_interval=dt.timedelta(seconds=10),
                                maximum_interval=dt.timedelta(minutes=1),
                                maximum_attempts=5,
                            ),
                        )
                except Exception:
                    logger.exception(
                        "Failed to roll back slot transitions after mutation failure",
                        workflow_run_id=workflow_run_id,
                    )
                raise

        if assignment.assigned_slot_ids:
            await workflow.execute_activity(
                activate_slots,
                ActivateSlotsInputs(slot_ids=assignment.assigned_slot_ids),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=1),
                    maximum_attempts=5,
                ),
            )

        if assignment.compacted_slot_ids:
            await workflow.execute_activity(
                finalize_compaction,
                FinalizeCompactionInputs(slot_ids=assignment.compacted_slot_ids),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=1),
                    maximum_attempts=5,
                ),
            )

        logger.info(
            "Batched dmat workflow completed",
            workflow_run_id=workflow_run_id,
            pending_count=len(assignment.assigned_slot_ids),
            compacted_count=len(assignment.compacted_slot_ids),
            column_count=len(assignment.assignments),
        )
