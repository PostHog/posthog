"""Activities for materialized property backfill workflow."""

import dataclasses
from typing import Optional

import structlog
from temporalio import activity

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.models import MaterializedColumnSlot
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.property_definition import PropertyType

logger = structlog.get_logger(__name__)

PROPERTY_TYPE_TO_COLUMN_NAME: dict[str, str] = {
    PropertyType.String: "string",
    PropertyType.Numeric: "numeric",
    PropertyType.Boolean: "bool",
    PropertyType.Datetime: "datetime",
}

MATERIALIZABLE_PROPERTY_TYPES: set[str] = set(PROPERTY_TYPE_TO_COLUMN_NAME.keys())


@dataclasses.dataclass
class GetSlotDetailsInputs:
    slot_id: str


@dataclasses.dataclass
class SlotDetails:
    team_id: int
    property_name: str
    property_type: str
    slot_index: int
    mat_column_name: str


@dataclasses.dataclass
class BackfillMaterializedColumnInputs:
    team_id: int
    property_name: str
    property_type: str
    mat_column_name: str
    partition_id: Optional[str] = None


@dataclasses.dataclass
class UpdateSlotStateInputs:
    slot_id: str
    state: str
    error_message: Optional[str] = None


def _generate_property_extraction_sql(property_name: str, property_type: str) -> str:
    """
    Generate SQL expression to extract property value from JSON properties column.

    Mimics the HogQL property type wrappers (toFloat, toBool, toDateTime) applied
    to JSON-extracted values to ensure identical behavior.
    """
    # Base JSON extraction with quote trimming (same as HogQL printer)
    base_extract = trim_quotes_expr(f"JSONExtractRaw(properties, '{property_name}')")

    if property_type == PropertyType.String:
        return base_extract

    elif property_type == PropertyType.Numeric:
        # Match HogQL's toFloat() - no whitespace trimming, just direct conversion
        return f"toFloat64OrNull({base_extract})"

    elif property_type == PropertyType.Boolean:
        # Match HogQL's toBool(transform(toString(...), ["true", "false"], [1, 0], None))
        # Need to use toString() wrapper to match HogQL behavior
        return f"transform(toString({base_extract}), ['true', 'false'], [1, 0], NULL)"

    elif property_type == PropertyType.Datetime:
        # Match HogQL's toDateTime() which uses parseDateTimeBestEffort
        return f"""coalesce(
            parseDateTimeBestEffortOrNull({base_extract}),
            parseDateTimeBestEffortOrNull(substring({base_extract}, 1, 10))
        )"""

    else:
        raise ValueError(f"Unsupported property type for materialization: {property_type}")


@activity.defn
def get_slot_details(inputs: GetSlotDetailsInputs) -> SlotDetails:
    """
    Get details about a materialized column slot from the database.

    Returns slot information including property name, type, and the target column name.
    """
    try:
        slot = MaterializedColumnSlot.objects.select_related("property_definition", "team").get(id=inputs.slot_id)
    except MaterializedColumnSlot.DoesNotExist:
        raise ValueError(f"MaterializedColumnSlot {inputs.slot_id} not found")

    property_definition = slot.property_definition
    if not property_definition:
        raise ValueError(f"MaterializedColumnSlot {inputs.slot_id} has no property_definition")

    type_name = PROPERTY_TYPE_TO_COLUMN_NAME.get(slot.property_type)
    if not type_name:
        raise ValueError(
            f"Unsupported property type '{slot.property_type}' for materialized column. "
            f"Supported types: {', '.join(PROPERTY_TYPE_TO_COLUMN_NAME.keys())}"
        )
    mat_column_name = f"dmat_{type_name}_{slot.slot_index}"

    logger.info(
        "Retrieved slot details",
        slot_id=inputs.slot_id,
        team_id=slot.team_id,
        property_name=property_definition.name,
        property_type=slot.property_type,
        slot_index=slot.slot_index,
        mat_column_name=mat_column_name,
    )

    return SlotDetails(
        team_id=slot.team_id,
        property_name=property_definition.name,
        property_type=slot.property_type,
        slot_index=slot.slot_index,
        mat_column_name=mat_column_name,
    )


@activity.defn
def backfill_materialized_column(inputs: BackfillMaterializedColumnInputs) -> int:
    """
    Backfill a materialized column by running ALTER TABLE UPDATE on historical events.

    Returns the number of rows affected (from ClickHouse mutation info).
    """
    # Generate the SQL expression for extracting the property
    extraction_sql = _generate_property_extraction_sql(inputs.property_name, inputs.property_type)

    # Build the ALTER TABLE UPDATE query
    partition_clause = f"IN PARTITION '{inputs.partition_id}'" if inputs.partition_id else ""

    # Note: Using sharded_events table directly (not distributed table)
    query = f"""
        ALTER TABLE sharded_events
        UPDATE {inputs.mat_column_name} = {extraction_sql}
        {partition_clause}
        WHERE team_id = %(team_id)s
    """

    logger.info(
        "Starting backfill for materialized column",
        team_id=inputs.team_id,
        property_name=inputs.property_name,
        property_type=inputs.property_type,
        mat_column_name=inputs.mat_column_name,
        partition_id=inputs.partition_id,
    )

    try:
        # Execute the ALTER TABLE UPDATE mutation
        sync_execute(query, {"team_id": inputs.team_id})

        # Note: ClickHouse mutations are async, so we can't get exact row count immediately
        # The mutation will complete in the background
        logger.info(
            "Backfill mutation submitted successfully",
            team_id=inputs.team_id,
            property_name=inputs.property_name,
            mat_column_name=inputs.mat_column_name,
        )

        # Return 0 since we don't have row count (mutation is async in ClickHouse)
        return 0

    except Exception as e:
        logger.exception(
            "Backfill failed",
            team_id=inputs.team_id,
            property_name=inputs.property_name,
            mat_column_name=inputs.mat_column_name,
            error=str(e),
        )
        raise


@activity.defn
def update_slot_state(inputs: UpdateSlotStateInputs) -> bool:
    """
    Update the state of a materialized column slot with activity logging.

    Returns True if update succeeded.
    """
    try:
        slot = MaterializedColumnSlot.objects.select_related("team", "property_definition").get(id=inputs.slot_id)
        old_state = slot.state

        slot.state = inputs.state

        # Store or clear error message
        if inputs.error_message:
            slot.error_message = inputs.error_message
            logger.error(
                "Slot state update with error",
                slot_id=inputs.slot_id,
                old_state=old_state,
                new_state=inputs.state,
                error_message=inputs.error_message,
            )
        elif inputs.state == "BACKFILL":
            # Clear error message when transitioning to BACKFILL (e.g., on retry)
            slot.error_message = None

        slot.save()

        logger.info(
            "Updated slot state",
            slot_id=inputs.slot_id,
            team_id=slot.team_id,
            old_state=old_state,
            new_state=inputs.state,
        )

        # Log activity for state transitions to READY or ERROR
        if inputs.state in ["READY", "ERROR"]:
            property_name = slot.property_definition.name if slot.property_definition else "Unknown"

            activity_name = (
                "materialized_column_backfill_completed"
                if inputs.state == "READY"
                else "materialized_column_backfill_failed"
            )

            log_activity(
                organization_id=slot.team.organization_id,
                team_id=slot.team_id,
                user=None,  # System user for workflow-triggered updates
                was_impersonated=False,
                item_id=str(slot.id),
                scope="DataManagement",
                activity=activity_name,
                detail=Detail(
                    name=property_name,
                    changes=[
                        Change(
                            type="MaterializedColumnSlot",
                            action="changed",
                            field="state",
                            before=old_state,
                            after=inputs.state,
                        ),
                    ],
                ),
            )

        return True

    except MaterializedColumnSlot.DoesNotExist:
        logger.warning("Slot not found for state update", slot_id=inputs.slot_id)
        return False
    except Exception as e:
        logger.exception("Failed to update slot state", slot_id=inputs.slot_id, error=str(e))
        raise
