"""
Dagster job to backfill ClickHouse events to customer-specific ducklings.

This job exports events from ClickHouse's `posthog.events` table to customer S3 buckets
as Parquet files, then registers those files with their DuckLake catalog.

Unlike the main DuckLake backfill (events_backfill_to_ducklake.py) which targets PostHog's
shared DuckLake, this job targets individual customer "ducklings" - isolated DuckLake
instances with their own RDS catalog and S3 bucket.

Architecture:
    DuckLakeCatalog (Django model)
        │ lookup by team_id
        ▼
    ClickHouse (events table)
        │ export via s3() - bucket policy allows ClickHouse EC2 role
        ▼
    Duckling S3 Bucket (parquet files)
        │ register via ducklake_add_data_files
        ▼
    Duckling RDS Catalog (PostgreSQL)

IAM Access:
    - ClickHouse EC2 role is allowed in duckling bucket policy (direct S3 access)
    - Dagster IRSA role can assume duckling cross-account roles (for DuckDB registration)

Partition Strategy:
    DynamicPartitionsDefinition with composite keys: {team_id}_{date}
    - team_id maps to duckling via DuckLakeCatalog
    - date is the partition date (YYYY-MM-DD)
"""

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

import boto3
import duckdb
import structlog
from botocore.exceptions import ClientError
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError
from dagster import (
    AssetExecutionContext,
    Config,
    DagsterRunStatus,
    DefaultSensorStatus,
    DynamicPartitionsDefinition,
    RunRequest,
    RunsFilter,
    SensorEvaluationContext,
    SensorResult,
    asset,
    define_asset_job,
    sensor,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import get_cluster
from posthog.clickhouse.query_tagging import tags_context
from posthog.cloud_utils import is_cloud
from posthog.dags.common.common import JobOwners, dagster_tags, settings_with_log_comment
from posthog.dags.events_backfill_to_ducklake import (
    DEFAULT_CLICKHOUSE_SETTINGS,
    EVENTS_COLUMNS,
    EXPECTED_DUCKLAKE_COLUMNS,
    MAX_RETRY_ATTEMPTS,
)
from posthog.ducklake.common import attach_catalog, escape, get_ducklake_catalog_for_team, get_team_config
from posthog.ducklake.models import DuckLakeCatalog
from posthog.ducklake.storage import configure_cross_account_connection

logger = structlog.get_logger(__name__)

BACKFILL_EVENTS_S3_PREFIX = "backfill/events"
BACKFILL_PERSONS_S3_PREFIX = "backfill/persons"

# Maximum partitions to create per sensor evaluation to avoid OOM/timeout
# The sensor runs daily, so this limits how fast full backfills progress
MAX_PARTITIONS_PER_FULL_BACKFILL_EVALUATION = 100

EVENTS_CONCURRENCY_TAG = {
    "duckling_events_backfill_concurrency": "duckling_events_v1",
}

PERSONS_CONCURRENCY_TAG = {
    "duckling_persons_backfill_concurrency": "duckling_persons_v1",
}

# Persons columns for export - joined with person_distinct_id2 to include distinct_ids
# This creates one row per distinct_id, with the person's properties denormalized
PERSONS_COLUMNS = """
    pd.team_id AS team_id,
    pd.distinct_id AS distinct_id,
    toString(p.id) AS id,
    p.properties AS properties,
    p.created_at AS created_at,
    p.is_identified AS is_identified,
    pd.version AS person_distinct_id_version,
    p.version AS person_version,
    p._timestamp AS _timestamp,
    NOW64() AS _inserted_at
"""

# Expected columns in the duckling's persons table for schema validation
EXPECTED_DUCKLAKE_PERSONS_COLUMNS = {
    "team_id",
    "distinct_id",
    "id",
    "properties",
    "created_at",
    "is_identified",
    "person_distinct_id_version",
    "person_version",
    "_timestamp",
    "_inserted_at",
}

duckling_events_partitions_def = DynamicPartitionsDefinition(name="duckling_events_backfill")
duckling_persons_partitions_def = DynamicPartitionsDefinition(name="duckling_persons_backfill")


class DucklingBackfillConfig(Config):
    """Config for duckling events backfill job."""

    clickhouse_settings: dict[str, Any] | None = None
    skip_ducklake_registration: bool = False
    skip_schema_validation: bool = False
    cleanup_prior_run_files: bool = True
    dry_run: bool = False


def parse_partition_key(key: str) -> tuple[int, str]:
    """Parse a partition key into team_id and date.

    Args:
        key: Partition key in format "{team_id}_{date}" (e.g., "12345_2024-01-15")

    Returns:
        Tuple of (team_id, date_str)

    Raises:
        ValueError: If the partition key format is invalid.
    """
    parts = key.rsplit("_", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid partition key format: {key}. Expected 'team_id_YYYY-MM-DD'")

    team_id_str, date_str = parts

    try:
        team_id = int(team_id_str)
    except ValueError as e:
        raise ValueError(f"Invalid team_id in partition key: {team_id_str}") from e

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"Invalid date in partition key: {date_str}") from e

    return team_id, date_str


def get_s3_url_for_clickhouse(bucket: str, region: str, path_without_scheme: str) -> str:
    """Build S3 URL in the format ClickHouse expects for cross-account access.

    ClickHouse uses the EC2 instance role for authentication. The duckling bucket
    policy explicitly allows the ClickHouse EC2 role, so no credentials needed.
    """
    return f"https://{bucket}.s3.{region}.amazonaws.com/{path_without_scheme}"


def get_earliest_event_date_for_team(team_id: int) -> datetime | None:
    """Query ClickHouse to find the earliest event date for a team.

    This is used by the full backfill sensor to determine the historical range
    of data to backfill.

    Returns:
        The date of the earliest event, or None if no events exist for this team.
    """
    cluster = get_cluster()
    workload = Workload.OFFLINE if is_cloud() else Workload.DEFAULT

    def query_earliest(client: Client) -> datetime | None:
        result = client.execute(
            """
            SELECT toDate(min(timestamp)) as earliest_date
            FROM events
            WHERE team_id = %(team_id)s
            """,
            {"team_id": team_id},
        )
        if result and result[0][0]:
            # ClickHouse returns a date object, convert to datetime
            date_val = result[0][0]
            if isinstance(date_val, datetime):
                return date_val
            return datetime.combine(date_val, datetime.min.time())
        return None

    return cluster.any_host_by_role(
        fn=query_earliest,
        workload=workload,
        node_role=NodeRole.DATA,
    ).result()


def get_earliest_person_date_for_team(team_id: int) -> datetime | None:
    """Query ClickHouse to find the earliest person modification date for a team.

    Uses _timestamp (Kafka ingestion time) since persons don't have a natural
    event timestamp like events do.

    Returns:
        The date of the earliest person modification, or None if no persons exist.
    """
    cluster = get_cluster()
    workload = Workload.OFFLINE if is_cloud() else Workload.DEFAULT

    def query_earliest(client: Client) -> datetime | None:
        result = client.execute(
            """
            SELECT toDate(min(_timestamp)) as earliest_date
            FROM person
            WHERE team_id = %(team_id)s
            """,
            {"team_id": team_id},
        )
        if result and result[0][0]:
            date_val = result[0][0]
            if isinstance(date_val, datetime):
                return date_val
            return datetime.combine(date_val, datetime.min.time())
        return None

    return cluster.any_host_by_role(
        fn=query_earliest,
        workload=workload,
        node_role=NodeRole.DATA,
    ).result()


def validate_duckling_schema(
    context: AssetExecutionContext,
    catalog: DuckLakeCatalog,
) -> None:
    """Validate that the duckling's events table schema matches our export columns.

    This pre-flight check ensures we don't waste time exporting data that can't
    be registered with DuckLake due to schema mismatches.
    """
    destination = catalog.to_cross_account_destination()
    catalog_config = get_team_config(catalog.team_id)
    alias = "duckling"

    conn = duckdb.connect()
    try:
        configure_cross_account_connection(conn, destinations=[destination])

        try:
            attach_catalog(conn, catalog_config, alias=alias)
        except duckdb.CatalogException as exc:
            if alias not in str(exc):
                raise

        result = conn.execute(f"DESCRIBE {alias}.main.events").fetchall()
        ducklake_columns = {row[0] for row in result}

        missing_in_ducklake = EXPECTED_DUCKLAKE_COLUMNS - ducklake_columns
        if missing_in_ducklake:
            context.log.warning(
                f"Duckling events table is missing columns that we export: {missing_in_ducklake}. "
                "These columns will be added automatically by ducklake_add_data_files if the table "
                "supports schema evolution."
            )
            logger.warning(
                "duckling_schema_mismatch",
                team_id=catalog.team_id,
                missing_columns=list(missing_in_ducklake),
            )

        extra_in_ducklake = ducklake_columns - EXPECTED_DUCKLAKE_COLUMNS
        if extra_in_ducklake:
            context.log.info(f"Duckling has additional columns not in our export: {extra_in_ducklake}")

        context.log.info(
            f"Schema validation passed. Duckling has {len(ducklake_columns)} columns, "
            f"we export {len(EXPECTED_DUCKLAKE_COLUMNS)} columns."
        )
        logger.info(
            "duckling_schema_validation_passed",
            team_id=catalog.team_id,
            ducklake_columns=len(ducklake_columns),
            export_columns=len(EXPECTED_DUCKLAKE_COLUMNS),
        )

    finally:
        conn.close()


def validate_duckling_persons_schema(
    context: AssetExecutionContext,
    catalog: DuckLakeCatalog,
) -> None:
    """Validate that the duckling's persons table schema matches our export columns."""
    destination = catalog.to_cross_account_destination()
    catalog_config = get_team_config(catalog.team_id)
    alias = "duckling"

    conn = duckdb.connect()
    try:
        configure_cross_account_connection(conn, destinations=[destination])

        try:
            attach_catalog(conn, catalog_config, alias=alias)
        except duckdb.CatalogException as exc:
            if alias not in str(exc):
                raise

        result = conn.execute(f"DESCRIBE {alias}.main.persons").fetchall()
        ducklake_columns = {row[0] for row in result}

        missing_in_ducklake = EXPECTED_DUCKLAKE_PERSONS_COLUMNS - ducklake_columns
        if missing_in_ducklake:
            context.log.warning(
                f"Duckling persons table is missing columns that we export: {missing_in_ducklake}. "
                "These columns will be added automatically by ducklake_add_data_files if the table "
                "supports schema evolution."
            )
            logger.warning(
                "duckling_persons_schema_mismatch",
                team_id=catalog.team_id,
                missing_columns=list(missing_in_ducklake),
            )

        extra_in_ducklake = ducklake_columns - EXPECTED_DUCKLAKE_PERSONS_COLUMNS
        if extra_in_ducklake:
            context.log.info(f"Duckling persons has additional columns not in our export: {extra_in_ducklake}")

        context.log.info(
            f"Persons schema validation passed. Duckling has {len(ducklake_columns)} columns, "
            f"we export {len(EXPECTED_DUCKLAKE_PERSONS_COLUMNS)} columns."
        )
        logger.info(
            "duckling_persons_schema_validation_passed",
            team_id=catalog.team_id,
            ducklake_columns=len(ducklake_columns),
            export_columns=len(EXPECTED_DUCKLAKE_PERSONS_COLUMNS),
        )

    finally:
        conn.close()


def cleanup_prior_run_files(
    context: AssetExecutionContext,
    catalog: DuckLakeCatalog,
    team_id: int,
    partition_date: datetime,
    current_run_id: str,
    s3_prefix: str,
) -> int:
    """Clean up S3 files from prior failed runs for this partition.

    This prevents orphaned files from accumulating when runs fail partway through.
    Only deletes files that don't match the current run_id.

    Uses cross-account role assumption to access the duckling's S3 bucket.

    Args:
        context: Dagster asset execution context.
        catalog: The DuckLakeCatalog for this duckling.
        team_id: Team ID for the partition.
        partition_date: Date for the partition.
        current_run_id: Current Dagster run ID (files with this ID are preserved).
        s3_prefix: S3 prefix for the backfill (e.g., "backfill/events" or "backfill/persons").

    Returns the number of files deleted.
    """
    destination = catalog.to_cross_account_destination()

    # Assume the cross-account role to access the duckling's bucket
    sts_client = boto3.client("sts")
    assume_kwargs: dict[str, Any] = {
        "RoleArn": destination.role_arn,
        "RoleSessionName": "duckling-cleanup",
        "DurationSeconds": 900,  # 15 minutes
    }
    if destination.external_id:
        assume_kwargs["ExternalId"] = destination.external_id

    response = sts_client.assume_role(**assume_kwargs)
    credentials = response["Credentials"]

    s3_client = boto3.client(
        "s3",
        region_name=destination.region or "us-east-1",
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )

    year = partition_date.strftime("%Y")
    month = partition_date.strftime("%m")
    day = partition_date.strftime("%d")

    # List objects under the backfill prefix for this team and date
    prefix = f"{s3_prefix}/team_id={team_id}/year={year}/month={month}/day={day}/"

    deleted_count = 0
    paginator = s3_client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=catalog.bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            # Check if this file is not from our current run
            if not key.endswith(f"/{current_run_id}.parquet"):
                context.log.info(f"Deleting orphaned file: {key}")
                logger.info("duckling_cleanup_orphaned_file", key=key, bucket=catalog.bucket, team_id=team_id)
                try:
                    s3_client.delete_object(Bucket=catalog.bucket, Key=key)
                    deleted_count += 1
                except ClientError as e:
                    # Log and continue - don't fail the whole job for cleanup failures
                    context.log.warning(f"Failed to delete orphaned file {key}: {e}")
                    logger.warning(
                        "duckling_cleanup_delete_failed",
                        key=key,
                        bucket=catalog.bucket,
                        team_id=team_id,
                        error=str(e),
                    )

    if deleted_count > 0:
        context.log.info(f"Cleaned up {deleted_count} orphaned files from prior runs")
        logger.info(
            "duckling_cleanup_complete",
            deleted_count=deleted_count,
            team_id=team_id,
            partition_date=partition_date.isoformat(),
        )

    return deleted_count


@retry(
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type((ClickHouseError, OSError, TimeoutError)),
    reraise=True,
)
def _execute_export_with_retry(
    client: Client,
    export_sql: str,
    settings: dict[str, Any],
    info: str,
) -> None:
    """Execute export SQL with retry logic for transient failures."""
    try:
        client.execute(export_sql, settings=settings)
    except Exception as e:
        logger.warning(
            "duckling_export_retry",
            info=info,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


def export_events_to_duckling_s3(
    context: AssetExecutionContext,
    client: Client,
    config: DucklingBackfillConfig,
    catalog: DuckLakeCatalog,
    team_id: int,
    date: datetime,
    run_id: str,
    settings: dict[str, Any],
) -> str | None:
    """Export events for a team/date to the duckling's S3 bucket.

    ClickHouse uses its EC2 instance role for S3 access. The duckling bucket policy
    explicitly allows the ClickHouse EC2 role, so no explicit credentials are needed.

    Returns:
        S3 path that was written, or None if dry_run.
    """
    year = date.strftime("%Y")
    month = date.strftime("%m")
    day = date.strftime("%d")
    date_str = date.strftime("%Y-%m-%d")

    # Path without s3:// scheme for the HTTPS URL
    path_without_scheme = (
        f"{BACKFILL_EVENTS_S3_PREFIX}/team_id={team_id}/year={year}/month={month}/day={day}/{run_id}.parquet"
    )

    # ClickHouse needs HTTPS URL format for cross-account S3 access
    s3_url = get_s3_url_for_clickhouse(catalog.bucket, catalog.bucket_region, path_without_scheme)

    # S3 path with scheme for DuckLake registration
    s3_path = f"s3://{catalog.bucket}/{path_without_scheme}"

    where_clause = f"team_id = {team_id} AND toDate(timestamp) = '{date_str}'"

    # ClickHouse uses its EC2 instance role - no credentials needed
    # The duckling bucket policy allows the ClickHouse EC2 role
    export_sql = f"""
    INSERT INTO FUNCTION s3(
        '{s3_url}',
        'Parquet'
    )
    SELECT
        {EVENTS_COLUMNS}
    FROM events
    WHERE {where_clause}
    SETTINGS s3_truncate_on_insert=1, use_hive_partitioning=0
    """

    info = f"team_id={team_id}, date={date_str}"

    if config.dry_run:
        context.log.info(f"[DRY RUN] Would export with SQL: {export_sql[:800]}...")
        return None

    context.log.info(f"Exporting events for {info} to {s3_path}")
    logger.info(
        "duckling_export_start",
        team_id=team_id,
        date=date_str,
        s3_path=s3_path,
    )

    try:
        _execute_export_with_retry(client, export_sql, settings, info)
        context.log.info(f"Successfully exported events for {info}")
        logger.info("duckling_export_success", team_id=team_id, date=date_str)
        return s3_path
    except Exception:
        context.log.exception(f"Failed to export events for {info} after {MAX_RETRY_ATTEMPTS} attempts")
        logger.exception("duckling_export_failed", team_id=team_id, date=date_str)
        raise


def register_file_with_duckling(
    context: AssetExecutionContext,
    catalog: DuckLakeCatalog,
    s3_path: str,
    config: DucklingBackfillConfig,
) -> bool:
    """Register an exported Parquet file with the duckling's DuckLake catalog.

    Uses cross-account role assumption via IRSA. The Dagster worker's IAM role
    has permission to assume the duckling's cross-account S3 role.

    Args:
        context: Dagster asset execution context.
        catalog: The DuckLakeCatalog for this duckling.
        s3_path: S3 path of the Parquet file to register.
        config: Job configuration.

    Returns:
        True if registration succeeded, False otherwise.
    """
    if config.skip_ducklake_registration:
        context.log.info("Skipping DuckLake registration (skip_ducklake_registration=True)")
        return False

    if config.dry_run:
        context.log.info(f"[DRY RUN] Would register {s3_path} with DuckLake at {catalog.db_host}")
        return False

    destination = catalog.to_cross_account_destination()
    alias = "duckling"

    conn = duckdb.connect()

    try:
        # Configure cross-account S3 access using IRSA
        # Dagster's IAM role can assume the duckling's cross-account role
        configure_cross_account_connection(
            conn,
            destinations=[destination],
        )

        # Get the catalog config including password for RDS connection
        catalog_config = get_team_config(catalog.team_id)

        # Attach the duckling's catalog
        attach_catalog(conn, catalog_config, alias=alias)

        # Register the file
        context.log.info(f"Registering file with DuckLake: {s3_path}")
        conn.execute(f"CALL ducklake_add_data_files('{alias}', 'main.events', '{escape(s3_path)}')")

        context.log.info(f"Successfully registered: {s3_path}")
        logger.info("duckling_file_registered", s3_path=s3_path, team_id=catalog.team_id)
        return True

    except Exception:
        context.log.exception(f"Failed to register file {s3_path}")
        logger.exception("duckling_file_registration_failed", s3_path=s3_path, team_id=catalog.team_id)
        raise

    finally:
        conn.close()


def export_persons_to_duckling_s3(
    context: AssetExecutionContext,
    client: Client,
    config: DucklingBackfillConfig,
    catalog: DuckLakeCatalog,
    team_id: int,
    date: datetime,
    run_id: str,
    settings: dict[str, Any],
) -> str | None:
    """Export persons for a team/date to the duckling's S3 bucket.

    Exports persons joined with person_distinct_id2 to include distinct_ids.
    Uses _timestamp (Kafka ingestion time) for date filtering since persons
    don't have a natural event timestamp.

    The query uses ReplacingMergeTree deduplication with FINAL to get the
    latest version of each person and distinct_id mapping.

    Returns:
        S3 path that was written, or None if dry_run.
    """
    year = date.strftime("%Y")
    month = date.strftime("%m")
    day = date.strftime("%d")
    date_str = date.strftime("%Y-%m-%d")

    path_without_scheme = (
        f"{BACKFILL_PERSONS_S3_PREFIX}/team_id={team_id}/year={year}/month={month}/day={day}/{run_id}.parquet"
    )
    s3_url = get_s3_url_for_clickhouse(catalog.bucket, catalog.bucket_region, path_without_scheme)
    s3_path = f"s3://{catalog.bucket}/{path_without_scheme}"

    # Join person with person_distinct_id2 to get distinct_ids
    # Use FINAL to handle ReplacingMergeTree deduplication
    # Filter by _timestamp to get persons modified on this date
    export_sql = f"""
    INSERT INTO FUNCTION s3(
        '{s3_url}',
        'Parquet'
    )
    SELECT
        {PERSONS_COLUMNS}
    FROM person AS p FINAL
    INNER JOIN person_distinct_id2 AS pd FINAL ON p.id = pd.person_id AND p.team_id = pd.team_id
    WHERE p.team_id = {team_id}
      AND pd.team_id = {team_id}
      AND toDate(p._timestamp) = '{date_str}'
      AND p.is_deleted = 0
      AND pd.is_deleted = 0
    SETTINGS s3_truncate_on_insert=1, use_hive_partitioning=0
    """

    info = f"team_id={team_id}, date={date_str}"

    if config.dry_run:
        context.log.info(f"[DRY RUN] Would export persons with SQL: {export_sql[:800]}...")
        return None

    context.log.info(f"Exporting persons for {info} to {s3_path}")
    logger.info(
        "duckling_persons_export_start",
        team_id=team_id,
        date=date_str,
        s3_path=s3_path,
    )

    try:
        _execute_export_with_retry(client, export_sql, settings, info)
        context.log.info(f"Successfully exported persons for {info}")
        logger.info("duckling_persons_export_success", team_id=team_id, date=date_str)
        return s3_path
    except Exception:
        context.log.exception(f"Failed to export persons for {info} after {MAX_RETRY_ATTEMPTS} attempts")
        logger.exception("duckling_persons_export_failed", team_id=team_id, date=date_str)
        raise


def register_persons_file_with_duckling(
    context: AssetExecutionContext,
    catalog: DuckLakeCatalog,
    s3_path: str,
    config: DucklingBackfillConfig,
) -> bool:
    """Register an exported persons Parquet file with the duckling's DuckLake catalog."""
    if config.skip_ducklake_registration:
        context.log.info("Skipping DuckLake registration (skip_ducklake_registration=True)")
        return False

    if config.dry_run:
        context.log.info(f"[DRY RUN] Would register {s3_path} with DuckLake at {catalog.db_host}")
        return False

    destination = catalog.to_cross_account_destination()
    alias = "duckling"

    conn = duckdb.connect()

    try:
        configure_cross_account_connection(
            conn,
            destinations=[destination],
        )

        catalog_config = get_team_config(catalog.team_id)
        attach_catalog(conn, catalog_config, alias=alias)

        context.log.info(f"Registering persons file with DuckLake: {s3_path}")
        conn.execute(f"CALL ducklake_add_data_files('{alias}', 'main.persons', '{escape(s3_path)}')")

        context.log.info(f"Successfully registered persons: {s3_path}")
        logger.info("duckling_persons_file_registered", s3_path=s3_path, team_id=catalog.team_id)
        return True

    except Exception:
        context.log.exception(f"Failed to register persons file {s3_path}")
        logger.exception("duckling_persons_file_registration_failed", s3_path=s3_path, team_id=catalog.team_id)
        raise

    finally:
        conn.close()


@asset(
    partitions_def=duckling_events_partitions_def,
    name="duckling_events_backfill",
    tags={"owner": JobOwners.TEAM_DATA_STACK.value, **EVENTS_CONCURRENCY_TAG},
)
def duckling_events_backfill(context: AssetExecutionContext, config: DucklingBackfillConfig) -> None:
    """Backfill events from ClickHouse to a customer's duckling.

    This asset:
    1. Parses the partition key to get team_id and date
    2. Looks up the DuckLakeCatalog for the team
    3. Validates the duckling's schema compatibility (optional)
    4. Cleans up orphaned files from prior failed runs (optional)
    5. Exports events to the duckling's S3 bucket (ClickHouse EC2 role has bucket access)
    6. Registers the Parquet file with the duckling's DuckLake catalog (via cross-account role)
    """
    team_id, date_str = parse_partition_key(context.partition_key)
    partition_date = datetime.strptime(date_str, "%Y-%m-%d")
    run_id = context.run.run_id[:8]

    context.log.info(f"Starting duckling backfill for team_id={team_id}, date={date_str}")
    logger.info(
        "duckling_backfill_start",
        team_id=team_id,
        date=date_str,
        run_id=run_id,
    )

    # Look up the duckling configuration
    catalog = get_ducklake_catalog_for_team(team_id)
    if catalog is None:
        raise ValueError(f"No DuckLakeCatalog found for team_id={team_id}")

    context.log.info(f"Found DuckLakeCatalog: bucket={catalog.bucket}, db_host={catalog.db_host}")

    # Validate schema before starting export (skip if dry_run or skip_ducklake_registration)
    if not config.dry_run and not config.skip_ducklake_registration and not config.skip_schema_validation:
        context.log.info("Validating duckling schema compatibility...")
        validate_duckling_schema(context, catalog)

    # Clean up orphaned files from prior failed runs
    if config.cleanup_prior_run_files and not config.dry_run:
        context.log.info("Cleaning up orphaned files from prior runs...")
        cleanup_prior_run_files(context, catalog, team_id, partition_date, run_id, BACKFILL_EVENTS_S3_PREFIX)

    # Prepare ClickHouse settings
    merged_settings = DEFAULT_CLICKHOUSE_SETTINGS.copy()
    merged_settings.update(settings_with_log_comment(context))
    if config.clickhouse_settings:
        merged_settings.update(config.clickhouse_settings)
        context.log.info(f"Using custom ClickHouse settings: {config.clickhouse_settings}")

    cluster = get_cluster()
    tags = dagster_tags(context)
    workload = Workload.OFFLINE if is_cloud() else Workload.DEFAULT

    def do_export(client: Client) -> str | None:
        with tags_context(kind="dagster", dagster=tags):
            return export_events_to_duckling_s3(
                context=context,
                client=client,
                config=config,
                catalog=catalog,
                team_id=team_id,
                date=partition_date,
                run_id=run_id,
                settings=merged_settings,
            )

    s3_path = cluster.any_host_by_role(
        fn=do_export,
        workload=workload,
        node_role=NodeRole.DATA,
    ).result()

    # Register with DuckLake if we have a file
    registered = False
    if s3_path:
        registered = register_file_with_duckling(context, catalog, s3_path, config)

    context.add_output_metadata(
        {
            "team_id": team_id,
            "partition_date": date_str,
            "s3_path": s3_path or "(dry run)",
            "registered": registered,
            "bucket": catalog.bucket,
        }
    )

    context.log.info(
        f"Completed duckling backfill for team_id={team_id}, date={date_str}: "
        f"exported={'yes' if s3_path else 'no'}, registered={'yes' if registered else 'no'}"
    )
    logger.info(
        "duckling_backfill_complete",
        team_id=team_id,
        date=date_str,
        s3_path=s3_path,
        registered=registered,
    )


@asset(
    partitions_def=duckling_persons_partitions_def,
    name="duckling_persons_backfill",
    tags={"owner": JobOwners.TEAM_DATA_STACK.value, **PERSONS_CONCURRENCY_TAG},
)
def duckling_persons_backfill(context: AssetExecutionContext, config: DucklingBackfillConfig) -> None:
    """Backfill persons from ClickHouse to a customer's duckling.

    This asset exports persons joined with person_distinct_id2 to include all
    distinct_ids associated with each person. Uses _timestamp for date partitioning
    since persons don't have a natural event timestamp.

    Steps:
    1. Parses the partition key to get team_id and date
    2. Looks up the DuckLakeCatalog for the team
    3. Validates the duckling's persons schema compatibility (optional)
    4. Cleans up orphaned files from prior failed runs (optional)
    5. Exports persons+distinct_ids to the duckling's S3 bucket
    6. Registers the Parquet file with the duckling's DuckLake catalog
    """
    team_id, date_str = parse_partition_key(context.partition_key)
    partition_date = datetime.strptime(date_str, "%Y-%m-%d")
    run_id = context.run.run_id[:8]

    context.log.info(f"Starting duckling persons backfill for team_id={team_id}, date={date_str}")
    logger.info(
        "duckling_persons_backfill_start",
        team_id=team_id,
        date=date_str,
        run_id=run_id,
    )

    catalog = get_ducklake_catalog_for_team(team_id)
    if catalog is None:
        raise ValueError(f"No DuckLakeCatalog found for team_id={team_id}")

    context.log.info(f"Found DuckLakeCatalog: bucket={catalog.bucket}, db_host={catalog.db_host}")

    if not config.dry_run and not config.skip_ducklake_registration and not config.skip_schema_validation:
        context.log.info("Validating duckling persons schema compatibility...")
        validate_duckling_persons_schema(context, catalog)

    if config.cleanup_prior_run_files and not config.dry_run:
        context.log.info("Cleaning up orphaned persons files from prior runs...")
        cleanup_prior_run_files(context, catalog, team_id, partition_date, run_id, BACKFILL_PERSONS_S3_PREFIX)

    merged_settings = DEFAULT_CLICKHOUSE_SETTINGS.copy()
    merged_settings.update(settings_with_log_comment(context))
    if config.clickhouse_settings:
        merged_settings.update(config.clickhouse_settings)
        context.log.info(f"Using custom ClickHouse settings: {config.clickhouse_settings}")

    cluster = get_cluster()
    tags = dagster_tags(context)
    workload = Workload.OFFLINE if is_cloud() else Workload.DEFAULT

    def do_export(client: Client) -> str | None:
        with tags_context(kind="dagster", dagster=tags):
            return export_persons_to_duckling_s3(
                context=context,
                client=client,
                config=config,
                catalog=catalog,
                team_id=team_id,
                date=partition_date,
                run_id=run_id,
                settings=merged_settings,
            )

    s3_path = cluster.any_host_by_role(
        fn=do_export,
        workload=workload,
        node_role=NodeRole.DATA,
    ).result()

    registered = False
    if s3_path:
        registered = register_persons_file_with_duckling(context, catalog, s3_path, config)

    context.add_output_metadata(
        {
            "team_id": team_id,
            "partition_date": date_str,
            "s3_path": s3_path or "(dry run)",
            "registered": registered,
            "bucket": catalog.bucket,
        }
    )

    context.log.info(
        f"Completed duckling persons backfill for team_id={team_id}, date={date_str}: "
        f"exported={'yes' if s3_path else 'no'}, registered={'yes' if registered else 'no'}"
    )
    logger.info(
        "duckling_persons_backfill_complete",
        team_id=team_id,
        date=date_str,
        s3_path=s3_path,
        registered=registered,
    )


@sensor(
    name="duckling_backfill_discovery_sensor",
    minimum_interval_seconds=3600,  # Run hourly
    job_name="duckling_events_backfill_job",
)
def duckling_backfill_discovery_sensor(context: SensorEvaluationContext) -> SensorResult:
    """Discover teams with DuckLakeCatalog entries and create daily backfill partitions.

    This sensor runs periodically to:
    1. Find all teams with DuckLakeCatalog configurations
    2. Create partitions for yesterday's data (if not already exists)
    3. Trigger backfill runs for new partitions
    4. Retry failed partitions that already exist
    """
    yesterday = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Get existing partitions
    existing = set(context.instance.get_dynamic_partitions("duckling_events_backfill"))

    new_partitions: list[str] = []
    run_requests: list[RunRequest] = []

    # Find all teams with duckling configurations
    for catalog in DuckLakeCatalog.objects.all():
        partition_key = f"{catalog.team_id}_{yesterday}"

        if partition_key not in existing:
            # New partition - create and trigger run
            new_partitions.append(partition_key)
            run_requests.append(
                RunRequest(
                    partition_key=partition_key,
                    run_key=f"{partition_key}_new",
                )
            )
            context.log.info(f"Creating partition for team_id={catalog.team_id}, date={yesterday}")
        else:
            # Existing partition - check if the last run failed and needs retry
            # Query for runs with this partition key (stored in dagster/partition tag)
            runs = context.instance.get_runs(
                filters=RunsFilter(
                    job_name="duckling_events_backfill_job",
                    tags={"dagster/partition": partition_key},
                ),
                limit=1,
            )
            if runs:
                latest_run = runs[0]
                # Only retry if failed - skip if in progress or succeeded
                if latest_run.status == DagsterRunStatus.FAILURE:
                    # Failed run - trigger retry with unique run_key
                    run_requests.append(
                        RunRequest(
                            partition_key=partition_key,
                            run_key=f"{partition_key}_retry_{latest_run.run_id[:8]}",
                        )
                    )
                    context.log.info(
                        f"Retrying failed partition team_id={catalog.team_id}, date={yesterday} "
                        f"(previous run: {latest_run.run_id[:8]})"
                    )
                    logger.info(
                        "duckling_sensor_retry_failed_partition",
                        team_id=catalog.team_id,
                        date=yesterday,
                        previous_run_id=latest_run.run_id,
                    )
                elif latest_run.status in (DagsterRunStatus.STARTED, DagsterRunStatus.QUEUED):
                    context.log.debug(
                        f"Skipping partition team_id={catalog.team_id}, date={yesterday} - run in progress"
                    )

    if new_partitions:
        context.log.info(f"Discovered {len(new_partitions)} new partitions to backfill")
        logger.info(
            "duckling_sensor_discovered_partitions",
            count=len(new_partitions),
            partitions=new_partitions,
        )

    if run_requests:
        logger.info(
            "duckling_sensor_run_requests",
            total_requests=len(run_requests),
            new_partitions=len(new_partitions),
            retries=len(run_requests) - len(new_partitions),
        )

    return SensorResult(
        run_requests=run_requests,
        dynamic_partitions_requests=[duckling_events_partitions_def.build_add_request(new_partitions)]
        if new_partitions
        else [],
    )


@sensor(
    name="duckling_full_backfill_sensor",
    minimum_interval_seconds=86400,  # Run daily when enabled
    job_name="duckling_events_backfill_job",
    default_status=DefaultSensorStatus.STOPPED,  # Disabled by default
)
def duckling_full_backfill_sensor(context: SensorEvaluationContext) -> SensorResult:
    """Full historical backfill sensor - disabled by default.

    This sensor is meant to be manually enabled via the Dagster UI when you need
    to do a full historical backfill for a new customer. It will:

    1. Query ClickHouse for the earliest event date for each team with a DuckLakeCatalog
    2. Create partitions for dates from earliest event to yesterday (batched)
    3. Trigger backfill runs for historical partitions

    The sensor creates at most MAX_PARTITIONS_PER_FULL_BACKFILL_EVALUATION partitions
    per evaluation to avoid OOM/timeout issues. Keep the sensor enabled until all
    partitions are created, then disable it.

    After the full backfill completes, you should disable this sensor and let
    the daily `duckling_backfill_discovery_sensor` handle ongoing daily top-ups.

    Usage:
        1. Create a DuckLakeCatalog entry for the customer in Django admin
        2. Enable this sensor via Dagster UI (Sensors tab -> Toggle on)
        3. Monitor the backfill progress in the Runs tab
        4. Disable this sensor once complete (when no new partitions are created)
    """
    yesterday = (timezone.now() - timedelta(days=1)).date()
    existing = set(context.instance.get_dynamic_partitions("duckling_events_backfill"))

    new_partitions: list[str] = []
    run_requests: list[RunRequest] = []
    total_partitions_created = 0

    for catalog in DuckLakeCatalog.objects.all():
        # Stop if we've hit the batch limit
        if total_partitions_created >= MAX_PARTITIONS_PER_FULL_BACKFILL_EVALUATION:
            context.log.info(
                f"Reached batch limit of {MAX_PARTITIONS_PER_FULL_BACKFILL_EVALUATION} partitions, "
                "will continue in next sensor evaluation"
            )
            break

        team_id = catalog.team_id

        # Query ClickHouse for the earliest event date
        earliest_date = get_earliest_event_date_for_team(team_id)
        if earliest_date is None:
            context.log.info(f"No events found for team_id={team_id}, skipping")
            continue

        earliest = earliest_date.date()
        team_partition_count = 0

        # Generate partitions from earliest date to yesterday
        current_date = earliest
        while current_date <= yesterday:
            # Stop if we've hit the batch limit
            if total_partitions_created >= MAX_PARTITIONS_PER_FULL_BACKFILL_EVALUATION:
                break

            date_str = current_date.strftime("%Y-%m-%d")
            partition_key = f"{team_id}_{date_str}"

            if partition_key not in existing:
                new_partitions.append(partition_key)
                run_requests.append(
                    RunRequest(
                        partition_key=partition_key,
                        run_key=f"{partition_key}_full_backfill",
                    )
                )
                team_partition_count += 1
                total_partitions_created += 1

            current_date += timedelta(days=1)

        if team_partition_count > 0:
            context.log.info(f"Team {team_id}: created {team_partition_count} new partitions (earliest: {earliest})")
            logger.info(
                "duckling_full_backfill_team_partitions",
                team_id=team_id,
                partition_count=team_partition_count,
                earliest_date=earliest.isoformat(),
                latest_date=yesterday.isoformat(),
            )

    if new_partitions:
        context.log.info(f"Full backfill: creating {len(new_partitions)} partitions this evaluation")
        logger.info(
            "duckling_full_backfill_discovered",
            partition_count=len(new_partitions),
            run_count=len(run_requests),
            batch_limit=MAX_PARTITIONS_PER_FULL_BACKFILL_EVALUATION,
        )
    else:
        context.log.info("Full backfill: no new partitions to create (all up to date)")

    return SensorResult(
        run_requests=run_requests,
        dynamic_partitions_requests=[duckling_events_partitions_def.build_add_request(new_partitions)]
        if new_partitions
        else [],
    )


duckling_events_backfill_job = define_asset_job(
    name="duckling_events_backfill_job",
    selection=["duckling_events_backfill"],
    tags={
        "owner": JobOwners.TEAM_DATA_STACK.value,
        "disable_slack_notifications": True,
        **EVENTS_CONCURRENCY_TAG,
    },
)


@sensor(
    name="duckling_persons_discovery_sensor",
    minimum_interval_seconds=3600,  # Run hourly
    job_name="duckling_persons_backfill_job",
)
def duckling_persons_discovery_sensor(context: SensorEvaluationContext) -> SensorResult:
    """Discover teams with DuckLakeCatalog entries and create daily persons partitions.

    Similar to duckling_backfill_discovery_sensor but for persons data.
    Uses _timestamp (Kafka ingestion time) for date filtering.
    """
    yesterday = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    existing = set(context.instance.get_dynamic_partitions("duckling_persons_backfill"))

    new_partitions: list[str] = []
    run_requests: list[RunRequest] = []

    for catalog in DuckLakeCatalog.objects.all():
        partition_key = f"{catalog.team_id}_{yesterday}"

        if partition_key not in existing:
            new_partitions.append(partition_key)
            run_requests.append(
                RunRequest(
                    partition_key=partition_key,
                    run_key=f"{partition_key}_persons_new",
                )
            )
            context.log.info(f"Creating persons partition for team_id={catalog.team_id}, date={yesterday}")
        else:
            runs = context.instance.get_runs(
                filters=RunsFilter(
                    job_name="duckling_persons_backfill_job",
                    tags={"dagster/partition": partition_key},
                ),
                limit=1,
            )
            if runs:
                latest_run = runs[0]
                # Only retry if failed - skip if in progress or succeeded
                if latest_run.status == DagsterRunStatus.FAILURE:
                    run_requests.append(
                        RunRequest(
                            partition_key=partition_key,
                            run_key=f"{partition_key}_persons_retry_{latest_run.run_id[:8]}",
                        )
                    )
                    context.log.info(f"Retrying failed persons partition team_id={catalog.team_id}, date={yesterday}")
                    logger.info(
                        "duckling_persons_sensor_retry_failed_partition",
                        team_id=catalog.team_id,
                        date=yesterday,
                        previous_run_id=latest_run.run_id,
                    )
                elif latest_run.status in (DagsterRunStatus.STARTED, DagsterRunStatus.QUEUED):
                    context.log.debug(
                        f"Skipping persons partition team_id={catalog.team_id}, date={yesterday} - run in progress"
                    )

    if new_partitions:
        context.log.info(f"Discovered {len(new_partitions)} new persons partitions to backfill")
        logger.info(
            "duckling_persons_sensor_discovered_partitions",
            count=len(new_partitions),
            partitions=new_partitions,
        )

    if run_requests:
        logger.info(
            "duckling_persons_sensor_run_requests",
            total_requests=len(run_requests),
            new_partitions=len(new_partitions),
            retries=len(run_requests) - len(new_partitions),
        )

    return SensorResult(
        run_requests=run_requests,
        dynamic_partitions_requests=[duckling_persons_partitions_def.build_add_request(new_partitions)]
        if new_partitions
        else [],
    )


@sensor(
    name="duckling_persons_full_backfill_sensor",
    minimum_interval_seconds=86400,  # Run daily when enabled
    job_name="duckling_persons_backfill_job",
    default_status=DefaultSensorStatus.STOPPED,  # Disabled by default
)
def duckling_persons_full_backfill_sensor(context: SensorEvaluationContext) -> SensorResult:
    """Full historical persons backfill sensor - disabled by default.

    Similar to duckling_full_backfill_sensor but for persons data.
    Queries min(_timestamp) from the person table to find the earliest date.

    The sensor creates at most MAX_PARTITIONS_PER_FULL_BACKFILL_EVALUATION partitions
    per evaluation to avoid OOM/timeout issues.

    Usage:
        1. Create a DuckLakeCatalog entry for the customer in Django admin
        2. Enable this sensor via Dagster UI (Sensors tab -> Toggle on)
        3. Monitor the backfill progress in the Runs tab
        4. Disable this sensor once complete (when no new partitions are created)
    """
    yesterday = (timezone.now() - timedelta(days=1)).date()
    existing = set(context.instance.get_dynamic_partitions("duckling_persons_backfill"))

    new_partitions: list[str] = []
    run_requests: list[RunRequest] = []
    total_partitions_created = 0

    for catalog in DuckLakeCatalog.objects.all():
        # Stop if we've hit the batch limit
        if total_partitions_created >= MAX_PARTITIONS_PER_FULL_BACKFILL_EVALUATION:
            context.log.info(
                f"Reached batch limit of {MAX_PARTITIONS_PER_FULL_BACKFILL_EVALUATION} partitions, "
                "will continue in next sensor evaluation"
            )
            break

        team_id = catalog.team_id

        earliest_date = get_earliest_person_date_for_team(team_id)
        if earliest_date is None:
            context.log.info(f"No persons found for team_id={team_id}, skipping")
            continue

        earliest = earliest_date.date()
        team_partition_count = 0

        current_date = earliest
        while current_date <= yesterday:
            # Stop if we've hit the batch limit
            if total_partitions_created >= MAX_PARTITIONS_PER_FULL_BACKFILL_EVALUATION:
                break

            date_str = current_date.strftime("%Y-%m-%d")
            partition_key = f"{team_id}_{date_str}"

            if partition_key not in existing:
                new_partitions.append(partition_key)
                run_requests.append(
                    RunRequest(
                        partition_key=partition_key,
                        run_key=f"{partition_key}_persons_full_backfill",
                    )
                )
                team_partition_count += 1
                total_partitions_created += 1

            current_date += timedelta(days=1)

        if team_partition_count > 0:
            context.log.info(
                f"Team {team_id}: created {team_partition_count} new persons partitions (earliest: {earliest})"
            )
            logger.info(
                "duckling_persons_full_backfill_team_partitions",
                team_id=team_id,
                partition_count=team_partition_count,
                earliest_date=earliest.isoformat(),
                latest_date=yesterday.isoformat(),
            )

    if new_partitions:
        context.log.info(f"Persons full backfill: creating {len(new_partitions)} partitions this evaluation")
        logger.info(
            "duckling_persons_full_backfill_discovered",
            partition_count=len(new_partitions),
            run_count=len(run_requests),
            batch_limit=MAX_PARTITIONS_PER_FULL_BACKFILL_EVALUATION,
        )
    else:
        context.log.info("Persons full backfill: no new partitions to create (all up to date)")

    return SensorResult(
        run_requests=run_requests,
        dynamic_partitions_requests=[duckling_persons_partitions_def.build_add_request(new_partitions)]
        if new_partitions
        else [],
    )


duckling_persons_backfill_job = define_asset_job(
    name="duckling_persons_backfill_job",
    selection=["duckling_persons_backfill"],
    tags={
        "owner": JobOwners.TEAM_DATA_STACK.value,
        "disable_slack_notifications": True,
        **PERSONS_CONCURRENCY_TAG,
    },
)
