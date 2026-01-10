"""Workflow for backfilling EAV property tables."""

import json
import datetime as dt
import dataclasses

import structlog
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.models.materialized_column_slots import MaterializedColumnSlotState
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.eav_backfill.activities import (
    BackfillEAVPropertyInputs,
    UpdateEAVSlotStateInputs,
    backfill_eav_property,
    update_eav_slot_state,
)


@dataclasses.dataclass
class BackfillEAVPropertyWorkflowInputs:
    """Inputs for the EAV property backfill workflow."""

    team_id: int
    slot_id: str
    property_name: str
    property_type: str
    # Wait time for ingestion cache refresh (default 180s, can be 0 for tests)
    cache_refresh_wait_seconds: int = 180
    # Retry interval for state updates (default 10s, can be shorter for tests)
    state_update_retry_interval_seconds: int = 10


@workflow.defn(name="backfill-eav-property")
class BackfillEAVPropertyWorkflow(PostHogWorkflow):
    """
    Workflow to backfill an EAV (Entity-Attribute-Value) property table.

    Flow:
    1. Wait 3 minutes for plugin-server ingestion cache to refresh
       (ensures no gap between backfill and future new events being materialized)
    2. Run INSERT INTO ... SELECT to backfill historical events into event_properties
    3. Update slot state to READY (or ERROR if failed)
    """

    @classmethod
    def parse_inputs(cls, inputs: list[str]) -> BackfillEAVPropertyWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return BackfillEAVPropertyWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: BackfillEAVPropertyWorkflowInputs) -> None:
        """Execute the EAV backfill workflow."""
        logger = structlog.get_logger("backfill_eav_property")

        try:
            # Wait for plugin-server cache to refresh before backfilling, to prevent
            # a gap where events arrive after backfill but before ingestion knows the property has been materialized.
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
                "Starting EAV backfill",
                team_id=inputs.team_id,
                property_name=inputs.property_name,
                property_type=inputs.property_type,
            )
            await workflow.execute_activity(
                backfill_eav_property,
                BackfillEAVPropertyInputs(
                    team_id=inputs.team_id,
                    property_name=inputs.property_name,
                    property_type=inputs.property_type,
                ),
                start_to_close_timeout=dt.timedelta(hours=4),  # Longer timeout for large datasets
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(minutes=1),
                    maximum_interval=dt.timedelta(minutes=10),
                    maximum_attempts=3,
                ),
            )

            # Update state to READY
            logger.info("EAV backfill complete, updating state to READY", slot_id=inputs.slot_id)
            await workflow.execute_activity(
                update_eav_slot_state,
                UpdateEAVSlotStateInputs(slot_id=inputs.slot_id, state=MaterializedColumnSlotState.READY),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=inputs.state_update_retry_interval_seconds),
                    maximum_interval=dt.timedelta(minutes=1),
                    maximum_attempts=5,  # State update is important, retry more
                ),
            )

            logger.info("EAV workflow completed successfully", slot_id=inputs.slot_id)

        except Exception as e:
            # Update state to ERROR
            logger.exception("EAV workflow failed", slot_id=inputs.slot_id)

            try:
                await workflow.execute_activity(
                    update_eav_slot_state,
                    UpdateEAVSlotStateInputs(
                        slot_id=inputs.slot_id,
                        state=MaterializedColumnSlotState.ERROR,
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
