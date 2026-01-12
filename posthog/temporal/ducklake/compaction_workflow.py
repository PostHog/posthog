import re
from datetime import timedelta
from typing import NamedTuple

import structlog
from temporalio import activity, common, workflow

from posthog.ducklake.common import attach_catalog, get_config
from posthog.ducklake.storage import configure_connection
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.ducklake.compaction_types import DucklakeCompactionInput

logger = structlog.get_logger(__name__)

# Valid SQL identifier pattern (alphanumeric and underscores only)
TABLE_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Valid file size pattern (e.g., "512MB", "1GB", "256KB")
FILE_SIZE_PATTERN = re.compile(r"^\d+\s*(B|KB|MB|GB|TB)$", re.IGNORECASE)


class TableInfo(NamedTuple):
    schema_name: str
    table_name: str


@activity.defn
async def run_ducklake_compaction(input: DucklakeCompactionInput) -> dict:
    """Run DuckLake compaction to merge small parquet files.

    This activity connects to DuckLake and runs merge_adjacent_files
    to consolidate small files into larger ones up to target_file_size.

    Uses HeartbeaterSync to send regular heartbeats in a background thread
    while synchronous DuckDB operations run, preventing heartbeat timeouts.
    """
    import duckdb

    logger.info(
        "Starting DuckLake compaction",
        target_file_size=input.target_file_size,
        tables=input.tables,
        dry_run=input.dry_run,
    )

    config = get_config()
    tables_to_compact: list[TableInfo] = []
    compaction_results: dict = {}

    # Use HeartbeaterSync to send regular heartbeats in a background thread
    # while synchronous DuckDB operations run
    with HeartbeaterSync(logger=logger):
        conn = duckdb.connect()

        try:
            # Configure S3 access and install DuckLake extension
            configure_connection(conn, install_extensions=True)

            # Attach the DuckLake catalog
            attach_catalog(conn, config, alias="ducklake")

            # Validate and set the target file size for compaction
            if not FILE_SIZE_PATTERN.match(input.target_file_size.strip()):
                raise ValueError(f"Invalid target_file_size format: {input.target_file_size!r}")
            conn.execute(f"CALL ducklake.set_option('target_file_size', '{input.target_file_size}')")

            # Get list of tables to compact
            if input.tables:
                # Input tables should be in "schema.table" format
                for table_spec in input.tables:
                    if "." in table_spec:
                        schema_name, table_name = table_spec.split(".", 1)
                        tables_to_compact.append(TableInfo(schema_name, table_name))
                    else:
                        # Assume main schema if not specified
                        tables_to_compact.append(TableInfo("main", table_spec))
            else:
                # Get all tables with their schema names from the ducklake catalog
                # Query the DuckLake metadata catalog to join tables with schemas
                result = conn.execute("""
                    SELECT s.schema_name, t.table_name
                    FROM ducklake_table_info('ducklake') t
                    JOIN __ducklake_metadata_ducklake.ducklake_schema s
                        ON t.schema_id = s.schema_id
                        AND s.end_snapshot IS NULL
                """).fetchall()
                tables_to_compact = [TableInfo(row[0], row[1]) for row in result]

            logger.info("Tables to compact", tables=[(t.schema_name, t.table_name) for t in tables_to_compact])

            for table_info in tables_to_compact:
                table_key = f"{table_info.schema_name}.{table_info.table_name}"

                # Validate table and schema names to prevent SQL injection
                if not TABLE_NAME_PATTERN.match(table_info.table_name):
                    logger.warning("Skipping invalid table name", table=table_key)
                    compaction_results[table_key] = {"status": "error", "error": "Invalid table name"}
                    continue
                if not TABLE_NAME_PATTERN.match(table_info.schema_name):
                    logger.warning("Skipping invalid schema name", table=table_key)
                    compaction_results[table_key] = {"status": "error", "error": "Invalid schema name"}
                    continue

                try:
                    if input.dry_run:
                        logger.info("Dry run - would compact table", table=table_key)
                        compaction_results[table_key] = {"status": "dry_run"}
                    else:
                        logger.info("Compacting table", table=table_key)
                        conn.execute(
                            f"CALL ducklake_merge_adjacent_files('ducklake', '{table_info.table_name}', "
                            f"schema => '{table_info.schema_name}')"
                        )
                        compaction_results[table_key] = {"status": "success"}
                        logger.info("Successfully compacted table", table=table_key)
                except Exception as e:
                    logger.exception("Failed to compact table", table=table_key, error=str(e))
                    compaction_results[table_key] = {"status": "error", "error": str(e)}
        finally:
            conn.close()

    logger.info("DuckLake compaction completed", results=compaction_results)

    return {
        "tables_processed": len(tables_to_compact),
        "results": compaction_results,
        "target_file_size": input.target_file_size,
        "dry_run": input.dry_run,
    }


@workflow.defn(name="ducklake-compaction")
class DucklakeCompactionWorkflow(PostHogWorkflow):
    """Workflow to compact DuckLake parquet files.

    This workflow merges small adjacent parquet files in DuckLake tables
    to improve query performance and reduce storage overhead.
    """

    @staticmethod
    def parse_inputs(input: list[str]) -> DucklakeCompactionInput:
        """Parse input from the management command CLI."""
        return DucklakeCompactionInput.model_validate_json(input[0]) if input else DucklakeCompactionInput()

    @workflow.run
    async def run(self, input: DucklakeCompactionInput) -> dict:
        """Run the DuckLake compaction workflow."""
        result = await workflow.execute_activity(
            run_ducklake_compaction,
            input,
            start_to_close_timeout=timedelta(hours=2),
            retry_policy=common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(minutes=1),
                maximum_interval=timedelta(minutes=10),
            ),
            heartbeat_timeout=timedelta(minutes=5),
        )
        return result
