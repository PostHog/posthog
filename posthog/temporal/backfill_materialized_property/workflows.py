"""Workflow for backfilling materialized property columns."""

import json
import datetime as dt
import dataclasses
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.backfill_materialized_property import PLUGIN_SERVER_TEAM_CACHE_TTL_SECONDS
from posthog.temporal.backfill_materialized_property.activities import (
    BackfillMaterializedColumnInputs,
    GetSlotDetailsInputs,
    UpdateSlotStateInputs,
    backfill_materialized_column,
    get_slot_details,
    update_slot_state,
)
from posthog.temporal.common.base import PostHogWorkflow


@dataclasses.dataclass
class BackfillMaterializedPropertyInputs:
    """Inputs for the backfill materialized property workflow."""

    team_id: int
    slot_id: str  # UUID of MaterializedColumnSlot
    partition_ids: Optional[list[str]] = None  # For future parallelization


@workflow.defn(name="backfill-materialized-property")
class BackfillMaterializedPropertyWorkflow(PostHogWorkflow):
    """
    Workflow to backfill a materialized property column.

    Flow:
    1. Wait 2 minutes for plugin-server ingestion cache to refresh
       (ensures no gap between backfill and future new events being materialized)
    2. Get slot details from database
    3. Run ClickHouse ALTER TABLE UPDATE to backfill historical events
    4. Update slot state to READY (or ERROR if failed)
    """

    @classmethod
    def parse_inputs(cls, inputs: list[str]) -> BackfillMaterializedPropertyInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return BackfillMaterializedPropertyInputs(**loaded)

    @workflow.run
    async def run(self, inputs: BackfillMaterializedPropertyInputs) -> None:
        """Execute the backfill workflow."""

        try:
            # Wait for plugin-server TeamManager cache to refresh
            # This prevents a gap where new events come in after backfill completes
            # but before the ingestion server knows about the new materialized column
            # (Plugin-server integration to populate new events comes later)
            workflow.logger.info(
                f"Waiting {PLUGIN_SERVER_TEAM_CACHE_TTL_SECONDS}s for ingestion cache refresh",
                team_id=inputs.team_id,
                slot_id=inputs.slot_id,
            )
            await workflow.sleep(dt.timedelta(seconds=PLUGIN_SERVER_TEAM_CACHE_TTL_SECONDS))

            # Get slot details
            workflow.logger.info("Getting slot details", slot_id=inputs.slot_id)
            slot_details = await workflow.execute_activity(
                get_slot_details,
                GetSlotDetailsInputs(slot_id=inputs.slot_id),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=1),
                    maximum_attempts=3,
                ),
            )

            # Run backfill
            workflow.logger.info(
                "Starting backfill",
                team_id=slot_details.team_id,
                property_name=slot_details.property_name,
                mat_column_name=slot_details.mat_column_name,
            )
            await workflow.execute_activity(
                backfill_materialized_column,
                BackfillMaterializedColumnInputs(
                    team_id=slot_details.team_id,
                    property_name=slot_details.property_name,
                    property_type=slot_details.property_type,
                    mat_column_name=slot_details.mat_column_name,
                    partition_id=None,  # For now, backfill all partitions at once
                ),
                start_to_close_timeout=dt.timedelta(hours=2),  # Backfill can take a while
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(minutes=1),
                    maximum_interval=dt.timedelta(minutes=10),
                    maximum_attempts=3,
                ),
            )

            # Update state to READY
            workflow.logger.info("Backfill complete, updating state to READY", slot_id=inputs.slot_id)
            await workflow.execute_activity(
                update_slot_state,
                UpdateSlotStateInputs(slot_id=inputs.slot_id, state="READY"),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=1),
                    maximum_attempts=5,  # State update is important, retry more
                ),
            )

            workflow.logger.info("Workflow completed successfully", slot_id=inputs.slot_id)

        except Exception as e:
            # Update state to ERROR
            workflow.logger.exception("Workflow failed", slot_id=inputs.slot_id, error=str(e))

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
                        initial_interval=dt.timedelta(seconds=10),
                        maximum_interval=dt.timedelta(minutes=1),
                        maximum_attempts=5,
                    ),
                )
            except Exception as state_update_error:
                workflow.logger.exception(
                    "Failed to update state to ERROR",
                    slot_id=inputs.slot_id,
                    original_error=str(e),
                    state_update_error=str(state_update_error),
                )

            # Re-raise the original exception
            raise
