"""Activities for EAV property backfill workflow."""

import dataclasses
from typing import Optional

import structlog
from temporalio import activity

from posthog.clickhouse.cluster import get_cluster
from posthog.models import MaterializedColumnSlot
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.event_properties.transformations import (
    boolean_transform,
    datetime_transform,
    numeric_transform,
    string_transform,
)
from posthog.models.materialized_column_slots import MaterializedColumnSlotState
from posthog.models.property_definition import PropertyType

logger = structlog.get_logger(__name__)

# Mapping from property type to EAV value column
PROPERTY_TYPE_TO_EAV_COLUMN: dict[str, str] = {
    str(PropertyType.String): "value_string",
    str(PropertyType.Numeric): "value_numeric",
    str(PropertyType.Boolean): "value_bool",
    str(PropertyType.Datetime): "value_datetime",
}


@dataclasses.dataclass
class BackfillEAVPropertyInputs:
    team_id: int
    property_name: str
    property_type: str


@dataclasses.dataclass
class UpdateEAVSlotStateInputs:
    slot_id: str
    state: str
    error_message: Optional[str] = None


def _generate_value_extraction_sql(property_type: str, value_column: str) -> str:
    """
    Generate SQL expression to extract property value from JSON and cast to appropriate type.

    Uses %(property_name)s placeholder for safe parameterization.
    Returns SQL that extracts the value and casts it for the target column.

    Transformation logic is shared with the MV in sql.py via transformations.py
    to ensure backfilled and newly ingested events produce identical results.
    """
    # Base JSON extraction with quote trimming and nullIf handling (same as HogQL printer)
    base_extract = (
        "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, %(property_name)s), ''), 'null'), '^\"|\"$', '')"
    )

    if property_type == PropertyType.String:
        return string_transform(base_extract)

    elif property_type == PropertyType.Numeric:
        return numeric_transform(base_extract)

    elif property_type == PropertyType.Boolean:
        return boolean_transform(base_extract)

    elif property_type == PropertyType.Datetime:
        return datetime_transform(base_extract)

    else:
        raise ValueError(f"Unsupported property type for EAV materialization: {property_type}")


@activity.defn
def backfill_eav_property(inputs: BackfillEAVPropertyInputs) -> int:
    """
    Backfill an EAV property by inserting rows into the event_properties table.

    This queries historical events that have the property set and inserts
    corresponding rows into the writable_event_properties table.

    Returns the approximate number of rows inserted.
    """
    value_column = PROPERTY_TYPE_TO_EAV_COLUMN.get(inputs.property_type)
    if not value_column:
        raise ValueError(f"Unsupported property type: {inputs.property_type}")

    value_extraction = _generate_value_extraction_sql(inputs.property_type, value_column)

    # Build the INSERT query
    # We select from events and insert into writable_event_properties
    # Only include events where the property exists (JSONHas check)
    query = f"""
        INSERT INTO writable_event_properties (
            team_id,
            timestamp,
            event,
            distinct_id,
            uuid,
            key,
            {value_column},
            _timestamp,
            _offset,
            _partition
        )
        SELECT
            team_id,
            timestamp,
            event,
            distinct_id,
            uuid,
            %(property_name)s AS key,
            {value_extraction} AS {value_column},
            now() AS _timestamp,
            0 AS _offset,
            0 AS _partition
        FROM events
        WHERE
            team_id = %(team_id)s
            AND JSONHas(properties, %(property_name)s)
            AND NOT isNull({value_extraction})
    """

    params = {
        "team_id": inputs.team_id,
        "property_name": inputs.property_name,
    }

    logger.info(
        "Starting EAV backfill",
        team_id=inputs.team_id,
        property_name=inputs.property_name,
        property_type=inputs.property_type,
        value_column=value_column,
    )

    try:
        cluster = get_cluster()

        # Execute on any node - the distributed table will route to correct shards
        def run_insert(client):
            client.execute(query, params)

        # Use a single node since writable_event_properties is a distributed table
        # that will route inserts to the correct shards
        cluster.any_host(run_insert).result()

        logger.info(
            "EAV backfill completed",
            team_id=inputs.team_id,
            property_name=inputs.property_name,
        )

        return 0  # We don't track exact row count for performance

    except Exception as e:
        logger.exception(
            "EAV backfill failed",
            team_id=inputs.team_id,
            property_name=inputs.property_name,
            error=str(e),
        )
        raise


@activity.defn
def update_eav_slot_state(inputs: UpdateEAVSlotStateInputs) -> bool:
    """
    Update the state of an EAV materialized column slot with activity logging.

    Returns True if update succeeded.
    """
    try:
        slot = MaterializedColumnSlot.objects.select_related("team").get(id=inputs.slot_id)
        old_state = slot.state

        slot.state = inputs.state

        # Store or clear error message
        if inputs.error_message:
            slot.error_message = inputs.error_message
            logger.error(
                "EAV slot state update with error",
                slot_id=inputs.slot_id,
                old_state=old_state,
                new_state=inputs.state,
                error_message=inputs.error_message,
            )
        elif inputs.state == MaterializedColumnSlotState.BACKFILL:
            # Clear error message when transitioning to BACKFILL (e.g., on retry)
            slot.error_message = None

        slot.save()

        logger.info(
            "Updated EAV slot state",
            slot_id=inputs.slot_id,
            team_id=slot.team_id,
            old_state=old_state,
            new_state=inputs.state,
        )

        # Log activity for state transitions to READY or ERROR
        if inputs.state in [MaterializedColumnSlotState.READY, MaterializedColumnSlotState.ERROR]:
            property_name = slot.property_name

            activity_name = (
                "eav_property_backfill_completed"
                if inputs.state == MaterializedColumnSlotState.READY
                else "eav_property_backfill_failed"
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
        logger.warning("EAV slot not found for state update", slot_id=inputs.slot_id)
        return False
    except Exception as e:
        logger.exception("Failed to update EAV slot state", slot_id=inputs.slot_id, error=str(e))
        raise
