import os
import django
from datetime import datetime
import pandas as pd

from dagster import (
    asset,
    AssetExecutionContext,
    Config,
    MetadataValue,
)

from posthog.clickhouse.client import sync_execute  # noqa
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.settings import (
    CLICKHOUSE_CLUSTER,
    CLICKHOUSE_HOST,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_USER,
    CLICKHOUSE_SECURE,
)

# setup PostHog Django Project
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()


class DeleteConfig(Config):
    team_id: int | None = None
    file_path: str = "/tmp/pending_person_deletions.parquet"
    run_id: str = datetime.now().strftime("%Y%m%d_%H%M%S")


def get_versioned_names(run_id: str) -> dict[str, str]:
    """Get versioned names for tables and dictionaries."""
    return {"table": f"pending_person_deletes_{run_id}", "dictionary": f"pending_person_deletes_dictionary_{run_id}"}


@asset
def pending_person_deletions(context: AssetExecutionContext, config: DeleteConfig) -> dict[str, str]:
    """Query postgres using django ORM to get pending person deletions and write to parquet."""

    if not config.team_id:
        # Use Django's queryset iterator for memory efficiency
        pending_deletions = (
            AsyncDeletion.objects.filter(deletion_type=DeletionType.Person, delete_verified_at__isnull=True)
            .values("team_id", "key", "created_at")
            .iterator()
        )
    else:
        pending_deletions = AsyncDeletion.objects.filter(
            deletion_type=DeletionType.Person,
            team_id=config.team_id,
            delete_verified_at__isnull=True,
        ).values("team_id", "key", "created_at")

    # Create a temporary directory for our parquet file
    output_path = config.file_path

    # Write to parquet in chunks
    chunk_size = 10000
    current_chunk = []
    total_rows = 0

    for deletion in pending_deletions:
        current_chunk.append(deletion)
        if len(current_chunk) >= chunk_size:
            if total_rows == 0:
                # First chunk, create new file
                pd.DataFrame(current_chunk).to_parquet(output_path, index=False)
            else:
                # Append to existing file
                pd.DataFrame(current_chunk).to_parquet(output_path, index=False, append=True)
            total_rows += len(current_chunk)
            current_chunk = []

    # Write any remaining records
    if current_chunk:
        if total_rows == 0:
            pd.DataFrame(current_chunk).to_parquet(output_path, index=False)
        else:
            pd.DataFrame(current_chunk).to_parquet(output_path, index=False, append=True)
        total_rows += len(current_chunk)

    context.add_output_metadata(
        {
            "total_rows": MetadataValue.int(total_rows),
            "file_path": MetadataValue.text(output_path),
            "file_size": MetadataValue.int(os.path.getsize(output_path)),
        }
    )

    return {"file_path": output_path, "total_rows": str(total_rows)}


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
    return {"table_name": names["table"]}


@asset(deps=[pending_person_deletions, create_pending_deletes_table])
def insert_pending_deletes(context: AssetExecutionContext, pending_person_deletions, create_pending_deletes_table):
    """Insert pending deletes from parquet file into ClickHouse merge tree using Arrow."""
    if not pending_person_deletions.get("total_rows", 0):
        return 0

    import pyarrow.parquet as pq
    from clickhouse_driver.client import Client

    # Read the parquet file into an Arrow table
    table = pq.read_table(pending_person_deletions["file_path"])

    # Rename the 'key' column to 'person_id' to match our schema
    table = table.rename_columns(["team_id", "person_id", "created_at"])

    # Create a ClickHouse client that supports Arrow
    client = Client(
        host=CLICKHOUSE_HOST,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        secure=CLICKHOUSE_SECURE,
        settings={"use_numpy": True},  # Required for Arrow support
    )

    # Insert the Arrow table directly
    client.execute(
        f"""
        INSERT INTO {create_pending_deletes_table["table_name"]} (team_id, person_id, created_at)
        VALUES
        """,
        table.to_pydict(),
        types_check=True,
        settings={
            "input_format_arrow_skip_columns": ["created_at"],  # Skip created_at as it's a default value
        },
    )

    context.add_output_metadata({"num_deletions": MetadataValue.int(pending_person_deletions["total_rows"])})

    return pending_person_deletions["total_rows"]


@asset(deps=[insert_pending_deletes])
def create_pending_deletes_dictionary(context: AssetExecutionContext, config: DeleteConfig):
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
def delete_person_events(context: AssetExecutionContext, config: DeleteConfig):
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
def cleanup_delete_assets(context: AssetExecutionContext, config: DeleteConfig):
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

    # Remove the temporary parquet file
    parquet_path = "/tmp/pending_person_deletions.parquet"
    if os.path.exists(parquet_path):
        os.remove(parquet_path)

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
