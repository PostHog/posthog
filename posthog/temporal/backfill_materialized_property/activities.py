"""Activities for materialized property backfill workflow."""

import dataclasses
from typing import Optional

import structlog
from temporalio import activity

from posthog.clickhouse.cluster import get_cluster
from posthog.models import MaterializedColumnSlot
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.property_definition import PropertyType

logger = structlog.get_logger(__name__)

PROPERTY_TYPE_TO_COLUMN_NAME: dict[str, str] = {
    str(PropertyType.String): "string",
    str(PropertyType.Numeric): "numeric",
    str(PropertyType.Boolean): "bool",
    str(PropertyType.Datetime): "datetime",
}

MATERIALIZABLE_PROPERTY_TYPES: set[str] = set(PROPERTY_TYPE_TO_COLUMN_NAME.keys())


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


def _generate_property_extraction_sql(property_type: str) -> str:
    """
    Generate SQL expression to extract property value from JSON properties column.

    Uses %(property_name)s placeholder for safe parameterization (matching HogQL pattern).
    Caller must pass property_name in the query params dict.

    Mimics the HogQL property type wrappers (toFloat, toBool, toDateTime) applied
    to JSON-extracted values to ensure identical behavior.
    """
    # Base JSON extraction with quote trimming and nullIf handling (same as HogQL printer)
    # HogQL pattern: replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(...), ''), 'null'), '^"|"$', '')
    base_extract = (
        "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, %(property_name)s), ''), 'null'), '^\"|\"$', '')"
    )

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
        # Match HogQL's toDateTime() -> parseDateTime64BestEffortOrNull with precision 6
        # See posthog/hogql/printer.py L1391-1392 and posthog/hogql/functions/clickhouse/conversions.py L112-127
        # Timezone param omitted - uses server default (UTC). Most datetime strings have explicit
        # timezone info anyway, and for ambiguous strings UTC is a reasonable default.
        return f"parseDateTime64BestEffortOrNull({base_extract}, 6)"

    else:
        raise ValueError(f"Unsupported property type for materialization: {property_type}")


@activity.defn
def backfill_materialized_column(inputs: BackfillMaterializedColumnInputs) -> int:
    """
    Backfill a materialized column by running ALTER TABLE UPDATE on historical events.

    Runs the mutation on all shards since sharded_events is a sharded table.
    Uses mutations_sync=1 to block until each shard's mutation completes.

    Returns 0 (row count not tracked).
    """
    extraction_sql = _generate_property_extraction_sql(inputs.property_type)

    partition_clause = "IN PARTITION %(partition_id)s" if inputs.partition_id else ""
    query = f"""
        ALTER TABLE sharded_events
        UPDATE {inputs.mat_column_name} = {extraction_sql}
        {partition_clause}
        WHERE team_id = %(team_id)s
    """

    params: dict[str, str | int] = {
        "team_id": inputs.team_id,
        "property_name": inputs.property_name,
    }
    if inputs.partition_id:
        params["partition_id"] = inputs.partition_id

    logger.info(
        "Starting backfill for materialized column",
        team_id=inputs.team_id,
        property_name=inputs.property_name,
        property_type=inputs.property_type,
        mat_column_name=inputs.mat_column_name,
        partition_id=inputs.partition_id,
    )

    try:
        cluster = get_cluster()

        # Execute mutation on one host per shard with mutations_sync=1
        # This blocks until the mutation completes on each shard
        def run_mutation(client):
            client.execute(query, params, settings={"mutations_sync": 1})

        cluster.map_one_host_per_shard(run_mutation).result()

        logger.info(
            "Backfill mutation completed on all shards",
            team_id=inputs.team_id,
            property_name=inputs.property_name,
            mat_column_name=inputs.mat_column_name,
        )

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
