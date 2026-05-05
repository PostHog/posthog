"""Workflows for backfilling materialized property columns.

Two workflows live here:

* ``BackfillMaterializedPropertiesBatchWorkflow`` — the weekly batched PENDING-allocation
  workflow described in the dynamic property materialization RFC. Picks up all PENDING slots,
  assigns them column indexes, syncs the (team_id, column_index) → property_name mapping
  to the ClickHouse-side dictionary source table, runs a single ``ALTER TABLE UPDATE`` whose
  SET clauses dispatch via ``dictGet`` against that dictionary, polls until the mutation
  completes on every shard, then transitions the slots to READY. Compaction is a separate
  workflow — see below.

* ``CompactMaterializedColumnsWorkflow`` — the weekly compaction workflow. Self-skips when
  the column pool has plenty of capacity. When triggered, it allocates dense compaction
  target columns for every existing READY slot, runs a single mutation that backfills the
  new columns, then swaps each slot's ``slot_index`` to the new dense index. Splitting this
  out from the PENDING workflow eliminates the deadlock where compaction targets and PENDING
  allocations would compete for the same depleted free pool inside one transaction.
"""

import json
import datetime as dt
import dataclasses

import structlog
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.backfill_materialized_property.activities import (
    ActivateSlotsInputs,
    AssignCompactionTargetsInputs,
    AssignCompactionTargetsResult,
    AssignPendingColumnsInputs,
    AssignPendingColumnsResult,
    ClearCompactionTargetsInputs,
    FailSlotsInputs,
    FinalizeCompactionInputs,
    PopulateSlotAssignmentsInputs,
    RunBatchedMutationInputs,
    activate_slots,
    assign_compaction_targets,
    assign_pending_columns,
    clear_compaction_targets,
    compute_cycle_marker_int,
    fail_slots,
    finalize_compaction,
    populate_slot_assignments,
    run_batched_mutation,
)
from posthog.temporal.common.base import PostHogWorkflow


@dataclasses.dataclass
class BackfillMaterializedPropertiesBatchInputs:
    """Inputs for the weekly batched dmat PENDING-allocation workflow."""

    # Wait time between assigning slots and submitting the mutation, so plugin-server
    # TeamManager caches refresh and start populating the new columns for fresh events
    # before the historical backfill mutation runs. Default 180s; tests can pass 0.
    cache_refresh_wait_seconds: int = 180


@workflow.defn(name="backfill-materialized-properties-batch")
class BackfillMaterializedPropertiesBatchWorkflow(PostHogWorkflow):
    """
    Weekly batched workflow that materializes all PENDING slots in one mutation.

    Compaction lives in a separate workflow (``CompactMaterializedColumnsWorkflow``) so the
    two paths never share a transaction or a free-column budget — splitting them removed a
    deadlock where compaction targets and PENDING allocations could compete for the same
    depleted free pool.

    Flow:
      1. Atomically assign each PENDING slot to a free column index for its team and
         transition it to BACKFILL.
      2. Sync the current (team_id, column_index) → property_name mapping to the
         ClickHouse-side ``dmat_slot_assignments`` table on every host and reload the
         ``dmat_slot_assignments_dict`` dictionary on every host. The mutation in
         step 4 reads from this dictionary at runtime.
      3. Sleep ~3 minutes so the plugin-server ingestion cache picks up the new
         (slot_index, property) mappings before the historical backfill runs.
      4. Submit a single ALTER TABLE UPDATE whose SET clauses dispatch via
         ``dictGet`` against the dictionary and whose WHERE prunes on
         ``team_id IN (SELECT DISTINCT team_id FROM dmat_slot_assignments)``. The
         mutation also embeds a per-cycle marker (``AND <hash> = <hash>``) so
         AlterTableMutationRunner's SQL-text dedup distinguishes cycles. Block until
         the mutation completes on every shard.
      5. Transition the assigned slots to READY. HogQL immediately starts using the
         materialized columns once the slots are READY.

    On any failure between steps 1 and 5, the affected slots are transitioned to ERROR
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
        # across activity retries — exactly what we need to make the assign activity idempotent
        # against a retry that hits a partially-committed PENDING→BACKFILL transition.
        run_id = workflow.info().run_id
        # Embedded in the mutation's WHERE clause as `AND <int> = <int>` so the formatted SQL
        # text differs across cycles. Without this, the dict-based mutation SQL would be
        # byte-identical week-to-week and AlterTableMutationRunner would reattach to the
        # previous cycle's already-completed mutation. Same hash across activity retries
        # within one run, different across runs. See `compute_cycle_marker_int` for details.
        cycle_marker_int = compute_cycle_marker_int(run_id)

        assignment: AssignPendingColumnsResult = await workflow.execute_activity(
            assign_pending_columns,
            AssignPendingColumnsInputs(run_id=run_id),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(minutes=1),
                maximum_attempts=3,
            ),
        )

        if not assignment.assigned_slot_ids:
            logger.info("Nothing to do — no PENDING slots", run_id=run_id)
            return

        # Sync the (team_id, column_index) → property_name mapping from Postgres to the
        # ClickHouse dict-source table on every host, then reload the dictionary cluster-
        # wide. The mutation that runs after the cache-refresh sleep reads from this dict.
        await workflow.execute_activity(
            populate_slot_assignments,
            PopulateSlotAssignmentsInputs(),
            start_to_close_timeout=dt.timedelta(minutes=10),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(minutes=1),
                maximum_attempts=3,
            ),
        )

        if inputs.cache_refresh_wait_seconds > 0:
            logger.info(
                "Waiting for ingestion cache refresh",
                wait_seconds=inputs.cache_refresh_wait_seconds,
                pending_count=len(assignment.assigned_slot_ids),
            )
            await workflow.sleep(dt.timedelta(seconds=inputs.cache_refresh_wait_seconds))

        if assignment.assignments:
            try:
                await workflow.execute_activity(
                    run_batched_mutation,
                    RunBatchedMutationInputs(
                        assignments=assignment.assignments,
                        cycle_marker_int=cycle_marker_int,
                    ),
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
                logger.exception("Batched mutation failed; rolling back slot transitions", run_id=run_id)
                try:
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
                except Exception:
                    logger.exception(
                        "Failed to roll back slot transitions after mutation failure",
                        run_id=run_id,
                    )
                raise

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

        logger.info(
            "Batched dmat PENDING workflow completed",
            run_id=run_id,
            pending_count=len(assignment.assigned_slot_ids),
            column_count=len(assignment.assignments),
        )


@dataclasses.dataclass
class CompactMaterializedColumnsInputs:
    """Inputs for the weekly dmat compaction workflow."""

    # See ``BackfillMaterializedPropertiesBatchInputs.cache_refresh_wait_seconds`` — same
    # purpose, but here the wait gives plugin-server time to start dual-writing to the new
    # compaction-target columns before the mutation backfills them. Tests can pass 0.
    cache_refresh_wait_seconds: int = 180


@workflow.defn(name="compact-materialized-columns")
class CompactMaterializedColumnsWorkflow(PostHogWorkflow):
    """
    Weekly compaction workflow. Self-skips on most weeks; only fires when the global free-
    column count drops below ``COMPACTION_FREE_COLUMN_THRESHOLD``. Estimated to actually
    perform work ~twice a year at the per-team rate the RFC anticipates.

    Flow:
      1. ``assign_compaction_targets`` either:
           - resumes any in-flight compactions from a prior run that crashed mid-finalize, or
           - if free_count is below threshold, plans dense compaction targets for every READY
             slot and writes ``compaction_target_slot_index`` (slots stay READY; plugin-server
             dual-writes to old AND new columns once caches refresh).
         If neither branch fires, the activity returns an empty result and the workflow exits.
      2. ``populate_slot_assignments`` syncs the current (team_id, column_index) → property
         mapping (including both ``slot_index`` and ``compaction_target_slot_index``) to the
         ClickHouse dict-source table and reloads the dictionary on every host. The mutation
         in step 4 reads from this dictionary at runtime.
      3. Sleep ~3 minutes so plugin-server picks up the new (slot_index,
         compaction_target_slot_index, property) mappings before the historical backfill runs.
      4. Submit a single ALTER TABLE UPDATE whose SET clauses dispatch via ``dictGet``
         against ``dmat_slot_assignments_dict``, populating the new compaction-target
         columns. Block until the mutation completes on every shard.
      5. ``finalize_compaction`` swaps each compacted slot's ``slot_index`` ←
         ``compaction_target_slot_index`` and clears the target. Slots stay READY through the
         swap — HogQL transparently switches columns on the next read.

    On any failure between steps 1 and 5, the affected slots stay READY on their original
    column (no read-side disruption — HogQL keeps reading the old column) and we clear
    ``compaction_target_slot_index`` so the cancelled new column is freed for reuse on the
    next cycle. Plugin-server stops dual-writing within ~3 minutes once caches refresh.
    """

    @classmethod
    def parse_inputs(cls, inputs: list[str]) -> CompactMaterializedColumnsInputs:
        loaded = json.loads(inputs[0]) if inputs else {}
        return CompactMaterializedColumnsInputs(**loaded)

    @workflow.run
    async def run(self, inputs: CompactMaterializedColumnsInputs) -> None:
        logger = structlog.get_logger("compact_materialized_columns")
        run_id = workflow.info().run_id
        # See the equivalent comment in BackfillMaterializedPropertiesBatchWorkflow.run —
        # the marker distinguishes this cycle's mutation from prior cycles' mutations
        # for AlterTableMutationRunner's SQL-text dedup.
        cycle_marker_int = compute_cycle_marker_int(run_id)

        assignment: AssignCompactionTargetsResult = await workflow.execute_activity(
            assign_compaction_targets,
            AssignCompactionTargetsInputs(run_id=run_id),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(minutes=1),
                maximum_attempts=3,
            ),
        )

        if not assignment.compacted_slot_ids:
            logger.info("Compaction not needed and no in-flight targets", run_id=run_id)
            return

        # Sync the (team_id, column_index) → property_name mapping from Postgres to the
        # ClickHouse dict-source table on every host, then reload the dictionary cluster-
        # wide. Includes both `slot_index` and `compaction_target_slot_index` rows, so the
        # mutation can backfill the new (target) column for every in-flight compaction.
        await workflow.execute_activity(
            populate_slot_assignments,
            PopulateSlotAssignmentsInputs(),
            start_to_close_timeout=dt.timedelta(minutes=10),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(minutes=1),
                maximum_attempts=3,
            ),
        )

        if inputs.cache_refresh_wait_seconds > 0:
            logger.info(
                "Waiting for ingestion cache refresh",
                wait_seconds=inputs.cache_refresh_wait_seconds,
                compacted_count=len(assignment.compacted_slot_ids),
            )
            await workflow.sleep(dt.timedelta(seconds=inputs.cache_refresh_wait_seconds))

        try:
            await workflow.execute_activity(
                run_batched_mutation,
                RunBatchedMutationInputs(
                    assignments=assignment.assignments,
                    cycle_marker_int=cycle_marker_int,
                ),
                start_to_close_timeout=dt.timedelta(hours=12),
                heartbeat_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(minutes=2),
                    maximum_interval=dt.timedelta(minutes=10),
                    maximum_attempts=3,
                ),
            )
        except Exception:
            logger.exception(
                "Compaction mutation failed; clearing targets so the next cycle re-plans",
                run_id=run_id,
            )
            try:
                # Compacted slots stay READY on their original column — their data is
                # untouched. Clearing `compaction_target_slot_index` frees the cancelled
                # new column and lets the next workflow run pick fresh targets.
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
                    "Failed to clear compaction targets after mutation failure",
                    run_id=run_id,
                )
            raise

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
            "Dmat compaction workflow completed",
            run_id=run_id,
            compacted_count=len(assignment.compacted_slot_ids),
            column_count=len(assignment.assignments),
        )
