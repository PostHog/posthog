"""Workflow for backfilling materialized property columns."""

import json
import datetime as dt
import dataclasses

import structlog
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.backfill_materialized_property.activities import (
    BackfillMaterializedColumnInputs,
    UpdateSlotStateInputs,
    backfill_materialized_column,
    update_slot_state,
)
from posthog.temporal.common.base import PostHogWorkflow


@dataclasses.dataclass
class BackfillMaterializedPropertyInputs:
    """Inputs for the backfill materialized property workflow."""

    team_id: int
    slot_id: str
    property_name: str
    property_type: str
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
                    property_type=inputs.property_type,
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
