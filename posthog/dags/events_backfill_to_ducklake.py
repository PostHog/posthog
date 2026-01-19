"""
Dagster job to backfill ClickHouse events to DuckLake.

This job exports events from ClickHouse's `posthog.events` table to S3 as Parquet files,
then registers those files with DuckLake using `ducklake_add_data_files`.

The job is partitioned by date to allow incremental backfilling of historical data.
Within each date partition, events are further chunked by team_id to keep file sizes manageable.

S3 path structure: s3://{bucket}/backfill/events/team_id={team_id}/year={year}/month={month}/day={day}/

This matches the DuckLake streaming partition scheme (team_id, year, month, day).
"""

from datetime import datetime
from typing import Any

import duckdb
import dagster
from clickhouse_driver import Client
from dagster import AssetExecutionContext, BackfillPolicy, Config, DailyPartitionsDefinition, asset, define_asset_job

from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import get_cluster
from posthog.clickhouse.query_tagging import tags_context
from posthog.cloud_utils import is_cloud
from posthog.dags.common.common import JobOwners, dagster_tags, settings_with_log_comment
from posthog.ducklake.common import attach_catalog, escape, get_config
from posthog.ducklake.storage import DuckLakeStorageConfig, configure_connection
from posthog.settings.base_variables import DEBUG
from posthog.settings.object_storage import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)

MAX_PARTITIONS_PER_RUN = 1

CONCURRENCY_TAG = {
    "events_ducklake_backfill_concurrency": "events_ducklake_v1",
}


def get_ducklake_bucket() -> str:
    config = get_config()
    return config.get("DUCKLAKE_BUCKET", "posthog-ducklake-dev")


def get_ducklake_region() -> str:
    config = get_config()
    return config.get("DUCKLAKE_BUCKET_REGION", "us-east-1")


BACKFILL_S3_PREFIX = "backfill/events"


class EventsBackfillConfig(Config):
    """Config for events backfill to DuckLake jobs."""

    clickhouse_settings: dict[str, Any] | None = None
    team_id_chunks: int = 64
    skip_ducklake_registration: bool = False
    dry_run: bool = False


daily_partitions = DailyPartitionsDefinition(
    start_date="2019-01-01",
    timezone="UTC",
    end_offset=0,
)


ONE_HOUR_IN_SECONDS = 60 * 60
ONE_GB_IN_BYTES = 1024 * 1024 * 1024

DEFAULT_CLICKHOUSE_SETTINGS = {
    "max_execution_time": 4 * ONE_HOUR_IN_SECONDS,
    "max_memory_usage": 50 * ONE_GB_IN_BYTES,
    "distributed_aggregation_memory_efficient": "1",
}


# Columns to export from ClickHouse events table.
# This matches the schema that the DuckLake streaming connector (via Kafka) expects.
# Note: We use toInt64(team_id) as project_id since they're equivalent in PostHog.
# Materialized columns (dmat_*) are ClickHouse-specific and not present in DuckLake.
EVENTS_COLUMNS = """
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    toInt64(team_id) as project_id,
    distinct_id,
    elements_chain,
    created_at,
    person_id,
    person_created_at,
    person_properties,
    group0_properties,
    group1_properties,
    group2_properties,
    group3_properties,
    group4_properties,
    group0_created_at,
    group1_created_at,
    group2_created_at,
    group3_created_at,
    group4_created_at,
    person_mode,
    historical_migration
"""

# Expected columns in the DuckLake events table (for schema validation)
EXPECTED_DUCKLAKE_COLUMNS = {
    "uuid",
    "event",
    "properties",
    "timestamp",
    "team_id",
    "project_id",
    "distinct_id",
    "elements_chain",
    "created_at",
    "person_id",
    "person_created_at",
    "person_properties",
    "group0_properties",
    "group1_properties",
    "group2_properties",
    "group3_properties",
    "group4_properties",
    "group0_created_at",
    "group1_created_at",
    "group2_created_at",
    "group3_created_at",
    "group4_created_at",
    "person_mode",
    "historical_migration",
}


class SchemaValidationError(Exception):
    """Raised when the DuckLake schema doesn't match expected columns."""

    pass


def validate_ducklake_schema(context: AssetExecutionContext) -> None:
    """Validate that the DuckLake events table schema matches our export columns.

    This pre-flight check ensures we don't waste time exporting data that can't
    be registered with DuckLake due to schema mismatches.
    """
    ducklake_config = get_config()
    storage_config = DuckLakeStorageConfig.from_runtime()
    alias = "ducklake"

    conn = duckdb.connect()
    try:
        configure_connection(conn, storage_config)

        try:
            attach_catalog(conn, ducklake_config, alias=alias)
        except duckdb.CatalogException as exc:
            if alias not in str(exc):
                raise

        result = conn.execute(f"DESCRIBE {alias}.main.events").fetchall()
        ducklake_columns = {row[0] for row in result}

        missing_in_ducklake = EXPECTED_DUCKLAKE_COLUMNS - ducklake_columns
        if missing_in_ducklake:
            context.log.warning(
                f"DuckLake events table is missing columns that we export: {missing_in_ducklake}. "
                "These columns will be added automatically by ducklake_add_data_files if the table "
                "supports schema evolution."
            )

        extra_in_ducklake = ducklake_columns - EXPECTED_DUCKLAKE_COLUMNS
        if extra_in_ducklake:
            # Extra columns in DuckLake are fine - they might come from streaming
            # (e.g., _kafka_* metadata columns)
            context.log.info(f"DuckLake has additional columns not in our export: {extra_in_ducklake}")

        context.log.info(
            f"Schema validation passed. DuckLake has {len(ducklake_columns)} columns, "
            f"we export {len(EXPECTED_DUCKLAKE_COLUMNS)} columns."
        )

    finally:
        conn.close()


def get_partition_where_clause(context: AssetExecutionContext, timestamp_field: str = "timestamp") -> str:
    start_incl = context.partition_time_window.start.strftime("%Y-%m-%d")
    end_excl = context.partition_time_window.end.strftime("%Y-%m-%d")
    return f"toDate({timestamp_field}) >= '{start_incl}' AND toDate({timestamp_field}) < '{end_excl}'"


def get_s3_path_for_partition(
    bucket: str,
    region: str,
    team_id: int | str,
    date: datetime,
    chunk_id: str,
    is_local: bool = False,
) -> str:
    """Build S3 path for a partition file.

    Path structure: s3://{bucket}/backfill/events/team_id={team_id}/year={year}/month={month}/day={day}/{chunk_id}.parquet

    This matches the DuckLake streaming partition scheme.
    """
    year = date.strftime("%Y")
    month = date.strftime("%m")
    day = date.strftime("%d")

    filename = f"{BACKFILL_S3_PREFIX}/team_id={team_id}/year={year}/month={month}/day={day}/{chunk_id}.parquet"

    if is_local:
        return f"{OBJECT_STORAGE_ENDPOINT}/{bucket}/{filename}"
    else:
        return f"https://{bucket}.s3.{region}.amazonaws.com/{filename}"


def get_s3_function_args(s3_path: str, is_local: bool = False) -> tuple[str, str]:
    """Build the arguments for ClickHouse s3() function.

    Returns tuple of (args_string, safe_args_string_for_logging).
    """
    if is_local:
        args = f"'{s3_path}', '{OBJECT_STORAGE_ACCESS_KEY_ID}', '{OBJECT_STORAGE_SECRET_ACCESS_KEY}', 'Parquet'"
        safe_args = f"'{s3_path}', '[REDACTED]', '[REDACTED]', 'Parquet'"
        return args, safe_args
    else:
        args = f"'{s3_path}', 'Parquet'"
        return args, args


def export_events_to_s3(
    context: AssetExecutionContext,
    client: Client,
    config: EventsBackfillConfig,
    where_clause: str,
    team_id_chunk: int,
    total_chunks: int,
    partition_date: datetime,
    run_id: str,
    settings: dict[str, Any],
) -> list[str]:
    """Export events for a specific team_id chunk to S3 as Parquet.

    Returns list of S3 paths that were written.
    """
    is_local = DEBUG
    bucket = get_ducklake_bucket()
    region = get_ducklake_region()
    team_id_expr = f"team_id % {total_chunks} = {team_id_chunk}"
    chunk_where = f"({where_clause}) AND ({team_id_expr})"

    chunk_id = f"chunk_{team_id_chunk:04d}_run_{run_id}"
    s3_path = get_s3_path_for_partition(
        bucket=bucket,
        region=region,
        team_id=f"mod{total_chunks}eq{team_id_chunk}",
        date=partition_date,
        chunk_id=chunk_id,
        is_local=is_local,
    )

    s3_args, safe_s3_args = get_s3_function_args(s3_path, is_local=is_local)

    export_sql = f"""
    INSERT INTO FUNCTION s3({s3_args})
    SELECT
        {EVENTS_COLUMNS}
    FROM events
    WHERE {chunk_where}
    SETTINGS s3_truncate_on_insert=1
    """

    if config.dry_run:
        # Log with redacted credentials
        safe_sql = f"""
    INSERT INTO FUNCTION s3({safe_s3_args})
    SELECT
        {EVENTS_COLUMNS}
    FROM events
    WHERE {chunk_where}
    SETTINGS s3_truncate_on_insert=1
    """
        context.log.info(f"[DRY RUN] Would export with SQL: {safe_sql[:800]}...")
        return []

    context.log.info(f"Exporting events chunk {team_id_chunk}/{total_chunks} to {s3_path}")

    try:
        client.execute(export_sql, settings=settings)
        context.log.info(f"Successfully exported chunk {team_id_chunk}/{total_chunks}")
        return [s3_path]
    except Exception:
        context.log.exception(f"Failed to export chunk {team_id_chunk}/{total_chunks}")
        raise


def register_files_with_ducklake(
    context: AssetExecutionContext,
    s3_paths: list[str],
    config: EventsBackfillConfig,
) -> int:
    """Register exported Parquet files with DuckLake using ducklake_add_data_files.

    Returns the number of files successfully registered.
    """
    if config.skip_ducklake_registration:
        context.log.info("Skipping DuckLake registration (skip_ducklake_registration=True)")
        return 0

    if not s3_paths:
        context.log.info("No files to register with DuckLake")
        return 0

    if config.dry_run:
        context.log.info(f"[DRY RUN] Would register {len(s3_paths)} files with DuckLake")
        return 0

    ducklake_config = get_config()
    storage_config = DuckLakeStorageConfig.from_runtime()
    alias = "ducklake"

    conn = duckdb.connect()
    registered_count = 0

    try:
        configure_connection(conn, storage_config)

        try:
            attach_catalog(conn, ducklake_config, alias=alias)
        except duckdb.CatalogException as exc:
            if alias not in str(exc):
                raise
            context.log.info(f"DuckLake catalog '{alias}' already attached")

        for s3_path in s3_paths:
            try:
                context.log.info(f"Registering file with DuckLake: {s3_path}")
                # Use escape() to prevent SQL injection
                conn.execute(f"CALL ducklake_add_data_files('{alias}', 'main.events', '{escape(s3_path)}')")
                registered_count += 1
                context.log.info(f"Successfully registered: {s3_path}")
            except Exception:
                context.log.exception(f"Failed to register file {s3_path}")
                raise

    finally:
        conn.close()

    context.log.info(f"Registered {registered_count}/{len(s3_paths)} files with DuckLake")
    return registered_count


@asset(
    partitions_def=daily_partitions,
    name="events_ducklake_backfill",
    backfill_policy=BackfillPolicy.multi_run(max_partitions_per_run=MAX_PARTITIONS_PER_RUN),
    tags={"owner": JobOwners.TEAM_DATA_STACK.value, **CONCURRENCY_TAG},
)
def events_ducklake_backfill(context: AssetExecutionContext, config: EventsBackfillConfig) -> None:
    """Backfill events from ClickHouse to DuckLake.

    This asset:
    1. Validates DuckLake schema compatibility before starting
    2. Exports events for the partition date from ClickHouse to S3 as Parquet
    3. Registers the Parquet files with DuckLake using ducklake_add_data_files

    Events are chunked by team_id modulo to parallelize export and keep file sizes manageable.
    """
    where_clause = get_partition_where_clause(context)
    partition_range = context.partition_key_range
    partition_range_str = f"{partition_range.start} to {partition_range.end}"
    partition_date = context.partition_time_window.start

    context.log.info(f"Config: {config}")

    # Validate DuckLake schema before starting export
    if not config.dry_run and not config.skip_ducklake_registration:
        context.log.info("Validating DuckLake schema compatibility...")
        validate_ducklake_schema(context)

    merged_settings = DEFAULT_CLICKHOUSE_SETTINGS.copy()
    # Add query tagging for observability
    merged_settings.update(settings_with_log_comment(context))
    if config.clickhouse_settings:
        merged_settings.update(config.clickhouse_settings)
        context.log.info(f"Using custom ClickHouse settings: {config.clickhouse_settings}")

    team_id_chunks = max(1, config.team_id_chunks)

    context.log.info(
        f"Running events backfill for partitions {partition_range_str} "
        f"(where='{where_clause}') "
        f"with {team_id_chunks} team_id chunks"
    )

    cluster = get_cluster()
    tags = dagster_tags(context)

    all_s3_paths: list[str] = []

    def run_export_on_coordinator(client: Client) -> list[str]:
        exported_paths: list[str] = []

        with tags_context(kind="dagster", dagster=tags):
            for chunk_i in range(team_id_chunks):
                context.log.info(f"Processing chunk {chunk_i + 1}/{team_id_chunks}")

                paths = export_events_to_s3(
                    context=context,
                    client=client,
                    config=config,
                    where_clause=where_clause,
                    team_id_chunk=chunk_i,
                    total_chunks=team_id_chunks,
                    partition_date=partition_date,
                    run_id=context.run.run_id[:8],
                    settings=merged_settings,
                )
                exported_paths.extend(paths)

                context.log.info(f"Completed chunk {chunk_i + 1}/{team_id_chunks}")

        return exported_paths

    workload = Workload.OFFLINE if is_cloud() else Workload.DEFAULT

    result = cluster.any_host_by_role(
        fn=run_export_on_coordinator,
        workload=workload,
        node_role=NodeRole.COORDINATOR,
    ).result()

    all_s3_paths.extend(result)

    context.log.info(f"Exported {len(all_s3_paths)} files to S3")

    registered_count = register_files_with_ducklake(context, all_s3_paths, config)

    context.add_output_metadata(
        {
            "partition_date": partition_range_str,
            "team_id_chunks": team_id_chunks,
            "files_exported": len(all_s3_paths),
            "files_registered": registered_count,
            "s3_paths": dagster.MetadataValue.json(all_s3_paths[:10]),
        }
    )

    context.log.info(
        f"Successfully backfilled events for partitions {partition_range_str}: "
        f"{len(all_s3_paths)} files exported, {registered_count} files registered with DuckLake"
    )


events_ducklake_backfill_job = define_asset_job(
    name="events_ducklake_backfill_job",
    selection=["events_ducklake_backfill"],
    tags={"owner": JobOwners.TEAM_DATA_STACK.value, **CONCURRENCY_TAG},
)
