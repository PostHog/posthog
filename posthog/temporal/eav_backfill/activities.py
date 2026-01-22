"""Activities for EAV property backfill workflow."""

import dataclasses
from typing import Optional

from django.conf import settings

import structlog
from temporalio import activity

from posthog.clickhouse.client.connection import NodeRole
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
# Note: DateTime uses value_string (not a separate column) to match traditional mat_* column behavior
PROPERTY_TYPE_TO_EAV_COLUMN: dict[str, str] = {
    str(PropertyType.String): "value_string",
    str(PropertyType.Numeric): "value_numeric",
    str(PropertyType.Boolean): "value_bool",
    str(PropertyType.Datetime): "value_string",
}


@dataclasses.dataclass
class GetBackfillMonthsInputs:
    team_id: int
    property_name: str


@dataclasses.dataclass
class BackfillEAVPropertyInputs:
    team_id: int
    property_name: str
    property_type: str
    # Month to backfill (format: YYYYMM, e.g. 202401 for January 2024)
    month: int


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
def get_backfill_months(inputs: GetBackfillMonthsInputs) -> list[int]:
    """
    Get the list of months (as YYYYMM integers) that have events with the given property.

    This is used to chunk the backfill into month-sized operations, aligned with
    the events table partition key (toYYYYMM(timestamp)).
    """
    query = """
        SELECT DISTINCT toYYYYMM(timestamp) as month
        FROM events
        WHERE
            team_id = %(team_id)s
            AND JSONHas(properties, %(property_name)s)
        ORDER BY month
    """

    params = {
        "team_id": inputs.team_id,
        "property_name": inputs.property_name,
    }

    logger.info(
        "Querying for months with property data",
        team_id=inputs.team_id,
        property_name=inputs.property_name,
    )

    cluster = get_cluster()

    def run_query(client):
        return client.execute(query, params)

    # Query can run on any data node
    result = cluster.any_host(run_query).result()
    months = [row[0] for row in result]

    logger.info(
        "Found months with property data",
        team_id=inputs.team_id,
        property_name=inputs.property_name,
        month_count=len(months),
        months=months,
    )

    return months


@activity.defn
def backfill_eav_property(inputs: BackfillEAVPropertyInputs) -> None:
    """
    Backfill an EAV property for a specific month.

    This queries historical events from the given month that have the property set
    and inserts corresponding rows into the writable_event_properties table.

    Month-based chunking aligns with the events table partition key (toYYYYMM),
    ensuring efficient partition pruning and bounded resource usage per operation.
    """
    value_column = PROPERTY_TYPE_TO_EAV_COLUMN.get(inputs.property_type)
    if not value_column:
        raise ValueError(f"Unsupported property type: {inputs.property_type}")

    value_extraction = _generate_value_extraction_sql(inputs.property_type, value_column)

    # Build the WHERE clause (month filter aligns with partition key for efficient pruning)
    where_conditions = [
        "team_id = %(team_id)s",
        "toYYYYMM(timestamp) = %(month)s",
        f"NOT isNull({value_extraction})",
    ]

    params: dict[str, int | str] = {
        "team_id": inputs.team_id,
        "property_name": inputs.property_name,
        "month": inputs.month,
    }

    where_clause = " AND ".join(where_conditions)

    # Build the INSERT query
    # We select from events and insert into writable_event_properties
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
            timestamp AS _timestamp,
            -1 AS _offset,
            -1 AS _partition
        FROM events
        WHERE {where_clause}
    """

    logger.info(
        "Starting EAV backfill",
        team_id=inputs.team_id,
        property_name=inputs.property_name,
        property_type=inputs.property_type,
        value_column=value_column,
        month=inputs.month,
    )

    try:
        cluster = get_cluster()

        def run_insert(client):
            client.execute(query, params)

        # writable_event_properties exists only on INGESTION_SMALL nodes in cloud.
        # In non-cloud environments, all tables exist on all nodes (see migration_tools.py)
        if settings.CLOUD_DEPLOYMENT:
            cluster.any_host_by_role(run_insert, NodeRole.INGESTION_SMALL).result()
        else:
            cluster.any_host(run_insert).result()

        logger.info(
            "EAV backfill completed",
            team_id=inputs.team_id,
            property_name=inputs.property_name,
            month=inputs.month,
        )

    except Exception as e:
        logger.exception(
            "EAV backfill failed",
            team_id=inputs.team_id,
            property_name=inputs.property_name,
            month=inputs.month,
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
