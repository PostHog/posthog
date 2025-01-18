from datetime import datetime
from clickhouse_driver.client import Client

from dagster import (
    asset,
    AssetExecutionContext,
    Config,
    MetadataValue,
)

from posthog.clickhouse.client import sync_execute
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.settings import (
    CLICKHOUSE_CLUSTER,
    CLICKHOUSE_HOST,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_USER,
    CLICKHOUSE_SECURE,
)


class DeleteConfig(Config):
    team_id: int | None = None
    run_id: str = datetime.now().strftime("%Y%m%d_%H%M%S")


def get_versioned_names(run_id: str) -> dict[str, str]:
    """Get versioned names for tables and dictionaries."""
    return {"table": f"pending_person_deletes_{run_id}", "dictionary": f"pending_person_deletes_dictionary_{run_id}"}


@asset
def create_pending_deletes_table(context: AssetExecutionContext, config: DeleteConfig):
    """Create a merge tree table in ClickHouse to store pending deletes."""
    names = get_versioned_names(config.run_id)
    sync_execute(
        f"""
        CREATE TABLE IF NOT EXISTS {names["table"]} ON CLUSTER '{CLICKHOUSE_CLUSTER}'
        (
            team_id Int64,
            person_id UUID,
            created_at DateTime DEFAULT now()
        )
        ENGINE = ReplacingMergeTree()
        ORDER BY (team_id, person_id)
        """
    )
    context.add_output_metadata({"table_name": MetadataValue.text(names["table"])})
    return {"table_name": names["table"]}


@asset(deps=[create_pending_deletes_table])
def pending_person_deletions(context: AssetExecutionContext, config: DeleteConfig, create_pending_deletes_table) -> int:
    """Query postgres using django ORM to get pending person deletions and insert directly into ClickHouse."""

    if not config.team_id:
        # Use Django's queryset iterator for memory efficiency
        pending_deletions = (
            AsyncDeletion.objects.filter(deletion_type=DeletionType.Person, delete_verified_at__isnull=True)
            .values("team_id", "key", "created_at")
            .iterator()
        )
    else:
        pending_deletions = (
            AsyncDeletion.objects.filter(
                deletion_type=DeletionType.Person,
                team_id=config.team_id,
                delete_verified_at__isnull=True,
            )
            .values("team_id", "key", "created_at")
            .iterator()
        )

    # Create a ClickHouse client
    client = Client(
        host=CLICKHOUSE_HOST,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        secure=CLICKHOUSE_SECURE,
    )

    # Process and insert in chunks
    chunk_size = 10000
    current_chunk = []
    total_rows = 0

    for deletion in pending_deletions:
        # Rename 'key' to 'person_id' to match our schema
        current_chunk.append(
            {"team_id": deletion["team_id"], "person_id": deletion["key"], "created_at": deletion["created_at"]}
        )

        if len(current_chunk) >= chunk_size:
            client.execute(
                f"""
                INSERT INTO {create_pending_deletes_table["table_name"]} (team_id, person_id, created_at)
                VALUES
                """,
                current_chunk,
            )
            total_rows += len(current_chunk)
            current_chunk = []

    # Insert any remaining records
    if current_chunk:
        client.execute(
            f"""
            INSERT INTO {create_pending_deletes_table["table_name"]} (team_id, person_id, created_at)
            VALUES
            """,
            current_chunk,
        )
        total_rows += len(current_chunk)

    context.add_output_metadata(
        {
            "total_rows": MetadataValue.int(total_rows),
            "table_name": MetadataValue.text(create_pending_deletes_table["table_name"]),
        }
    )

    return total_rows


@asset(deps=[pending_person_deletions])
def create_pending_deletes_dictionary(context: AssetExecutionContext, config: DeleteConfig, pending_person_deletions):
    """Create a dictionary table that wraps pending_person_deletes for efficient lookups."""
    names = get_versioned_names(config.run_id)
    sync_execute(
        f"""
        CREATE DICTIONARY IF NOT EXISTS {names["dictionary"]} ON CLUSTER '{CLICKHOUSE_CLUSTER}'
        (
            team_id Int64,
            person_id UUID,
            created_at DateTime
        )
        PRIMARY KEY team_id, person_id
        SOURCE(CLICKHOUSE(
            TABLE {names["table"]}
            USER '{CLICKHOUSE_USER}'
            PASSWORD '{CLICKHOUSE_PASSWORD}'
        ))
        LIFETIME(MIN 0 MAX 3600)
        LAYOUT(COMPLEX_KEY_HASHED())
        """
    )
    return {"dictionary_name": names["dictionary"]}


@asset(deps=[create_pending_deletes_dictionary])
def delete_person_events(context: AssetExecutionContext, config: DeleteConfig, create_pending_deletes_dictionary):
    """Delete events from sharded_events table for persons pending deletion."""

    # First check if there are any pending deletes
    names = get_versioned_names(config.run_id)
    count_result = sync_execute(
        f"""
        SELECT count()
        FROM {names["dictionary"]}
        """
    )[0][0]

    if count_result == 0:
        context.add_output_metadata({"events_deleted": MetadataValue.int(0), "message": "No pending deletions found"})
        return 0

    # Execute deletion using the dictionary for efficient lookups
    # We use ALTER TABLE DELETE instead of DELETE FROM because it's more efficient for large deletions
    deleted_count = sync_execute(
        f"""
        ALTER TABLE sharded_events ON CLUSTER '{CLICKHOUSE_CLUSTER}'
        DELETE WHERE (team_id, person_id) IN (
            SELECT team_id, person_id
            FROM {names["dictionary"]}
        )
        """,
        settings={
            "max_execution_time": 3600  # 1 hour timeout
        },
    )

    context.add_output_metadata(
        {
            "events_deleted": MetadataValue.int(count_result),
            "delete_count": MetadataValue.int(deleted_count),
            "message": f"Deleted events for {count_result} persons",
        }
    )

    return count_result


@asset(deps=[delete_person_events])
def cleanup_delete_assets(context: AssetExecutionContext, config: DeleteConfig, delete_person_events):
    """Clean up temporary tables, dictionary, and mark deletions as verified."""
    names = get_versioned_names(config.run_id)

    # Drop the dictionary
    sync_execute(
        f"""
        DROP DICTIONARY IF EXISTS {names["dictionary"]} ON CLUSTER '{CLICKHOUSE_CLUSTER}'
        """
    )

    # Drop the table
    sync_execute(
        f"""
        DROP TABLE IF EXISTS {names["table"]} ON CLUSTER '{CLICKHOUSE_CLUSTER}'
        """
    )

    # Mark deletions as verified in Django
    if not config.team_id:
        AsyncDeletion.objects.filter(deletion_type=DeletionType.Person, delete_verified_at__isnull=True).update(
            delete_verified_at=datetime.now()
        )
    else:
        AsyncDeletion.objects.filter(
            deletion_type=DeletionType.Person, team_id=config.team_id, delete_verified_at__isnull=True
        ).update(delete_verified_at=datetime.now())

    return True
