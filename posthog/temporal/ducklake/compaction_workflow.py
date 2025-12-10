import re
from datetime import timedelta

import structlog
from temporalio import activity, common, workflow

from posthog.ducklake.common import attach_catalog, configure_connection, get_config
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.ducklake.compaction_types import DucklakeCompactionInput

logger = structlog.get_logger(__name__)

# Valid SQL identifier pattern (alphanumeric and underscores only)
TABLE_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


@activity.defn
async def run_ducklake_compaction(input: DucklakeCompactionInput) -> dict:
    """Run DuckLake compaction to merge small parquet files.

    This activity connects to DuckLake and runs merge_adjacent_files
    to consolidate small files into larger ones up to target_file_size.
    """
    import duckdb

    logger.info(
        "Starting DuckLake compaction",
        target_file_size=input.target_file_size,
        tables=input.tables,
        dry_run=input.dry_run,
    )

    config = get_config()

    # Connect to DuckDB and attach DuckLake catalog
    conn = duckdb.connect()

    try:
        # Configure S3 access and install DuckLake extension
        configure_connection(conn, config, install_extension=True)

        # Attach the DuckLake catalog
        attach_catalog(conn, config, alias="ducklake")

        # Set the target file size for compaction
        conn.execute(f"CALL ducklake.set_option('target_file_size', '{input.target_file_size}')")

        activity.heartbeat()

        # Get list of tables to compact
        if input.tables:
            tables_to_compact = input.tables
        else:
            # Get all tables in the ducklake catalog
            result = conn.execute("""
                SELECT table_name
                FROM ducklake.information_schema.tables
                WHERE table_schema = 'main'
            """).fetchall()
            tables_to_compact = [row[0] for row in result]

        logger.info("Tables to compact", tables=tables_to_compact)

        compaction_results = {}

        for table in tables_to_compact:
            activity.heartbeat()

            # Validate table name to prevent SQL injection
            if not TABLE_NAME_PATTERN.match(table):
                logger.warning("Skipping invalid table name", table=table)
                compaction_results[table] = {"status": "error", "error": "Invalid table name"}
                continue

            try:
                if input.dry_run:
                    logger.info("Dry run - would compact table", table=table)
                    compaction_results[table] = {"status": "dry_run"}
                else:
                    logger.info("Compacting table", table=table)
                    conn.execute(f"CALL ducklake.merge_adjacent_files(table => '{table}')")
                    compaction_results[table] = {"status": "success"}
                    logger.info("Successfully compacted table", table=table)
            except Exception as e:
                logger.exception("Failed to compact table", table=table, error=str(e))
                compaction_results[table] = {"status": "error", "error": str(e)}
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
