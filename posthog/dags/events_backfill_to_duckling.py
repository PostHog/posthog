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
        │ export via s3() with cross-account IAM role
        ▼
    Duckling S3 Bucket (parquet files)
        │ register via ducklake_add_data_files
        ▼
    Duckling RDS Catalog (PostgreSQL)

Partition Strategy:
    DynamicPartitionsDefinition with composite keys: {team_id}_{date}
    - team_id maps to duckling via DuckLakeCatalog
    - date is the partition date (YYYY-MM-DD)
"""

from datetime import datetime, timedelta
from typing import Any

import duckdb
import structlog
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError
from dagster import (
    AssetExecutionContext,
    Config,
    DynamicPartitionsDefinition,
    RunRequest,
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
from posthog.dags.events_backfill_to_ducklake import DEFAULT_CLICKHOUSE_SETTINGS, EVENTS_COLUMNS, MAX_RETRY_ATTEMPTS
from posthog.ducklake.common import attach_catalog, escape
from posthog.ducklake.models import DuckLakeCatalog, get_team_catalog
from posthog.ducklake.storage import _get_cross_account_credentials, configure_cross_account_connection

logger = structlog.get_logger(__name__)

BACKFILL_S3_PREFIX = "backfill/events"

CONCURRENCY_TAG = {
    "duckling_events_backfill_concurrency": "duckling_events_v1",
}

duckling_backfill_partitions_def = DynamicPartitionsDefinition(name="duckling_events_backfill")


class DucklingBackfillConfig(Config):
    """Config for duckling events backfill job."""

    clickhouse_settings: dict[str, Any] | None = None
    skip_ducklake_registration: bool = False
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


def get_s3_path_for_duckling(
    bucket: str,
    team_id: int,
    date: datetime,
    run_id: str,
) -> str:
    """Build S3 path for a duckling partition file.

    Path structure: s3://{bucket}/backfill/events/team_id={team_id}/year={year}/month={month}/day={day}/{run_id}.parquet
    """
    year = date.strftime("%Y")
    month = date.strftime("%m")
    day = date.strftime("%d")

    return f"s3://{bucket}/{BACKFILL_S3_PREFIX}/team_id={team_id}/year={year}/month={month}/day={day}/{run_id}.parquet"


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

    Uses cross-account IAM role assumption to write directly to the customer's S3 bucket.

    Returns:
        S3 path that was written, or None if dry_run.
    """
    destination = catalog.to_cross_account_destination()

    # Get cross-account credentials for ClickHouse s3() function
    access_key, secret_key, session_token = _get_cross_account_credentials(
        destination.role_arn,
        destination.external_id,
    )

    s3_path = get_s3_path_for_duckling(
        bucket=destination.bucket,
        team_id=team_id,
        date=date,
        run_id=run_id,
    )

    # ClickHouse s3() function with explicit credentials including session token
    # Note: ClickHouse s3() function accepts session token as the 4th credential argument
    date_str = date.strftime("%Y-%m-%d")
    where_clause = f"team_id = {team_id} AND toDate(timestamp) = '{date_str}'"

    export_sql = f"""
    INSERT INTO FUNCTION s3(
        '{s3_path}',
        '{access_key}',
        '{secret_key}',
        '{session_token}',
        'Parquet'
    )
    SELECT
        {EVENTS_COLUMNS}
    FROM events
    WHERE {where_clause}
    SETTINGS s3_truncate_on_insert=1, use_hive_partitioning=0
    """

    # For logging, redact credentials
    safe_sql = f"""
    INSERT INTO FUNCTION s3(
        '{s3_path}',
        '[REDACTED]',
        '[REDACTED]',
        '[REDACTED]',
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
        context.log.info(f"[DRY RUN] Would export with SQL: {safe_sql[:800]}...")
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
        context.log.info(f"[DRY RUN] Would register {s3_path} with DuckLake")
        return False

    destination = catalog.to_cross_account_destination()
    catalog_config = catalog.to_config_dict()
    alias = "duckling"

    conn = duckdb.connect()

    try:
        # Configure cross-account S3 access
        configure_cross_account_connection(
            conn,
            role_arn=destination.role_arn,
            external_id=destination.external_id,
            region=destination.region,
        )

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


@asset(
    partitions_def=duckling_backfill_partitions_def,
    name="duckling_events_backfill",
    tags={"owner": JobOwners.TEAM_DATA_STACK.value, **CONCURRENCY_TAG},
)
def duckling_events_backfill(context: AssetExecutionContext, config: DucklingBackfillConfig) -> None:
    """Backfill events from ClickHouse to a customer's duckling.

    This asset:
    1. Parses the partition key to get team_id and date
    2. Looks up the DuckLakeCatalog for the team
    3. Exports events to the duckling's S3 bucket via cross-account IAM role
    4. Registers the Parquet file with the duckling's DuckLake catalog
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
    catalog = get_team_catalog(team_id)
    if catalog is None:
        raise ValueError(f"No DuckLakeCatalog found for team_id={team_id}")

    context.log.info(f"Found DuckLakeCatalog: bucket={catalog.s3_bucket}, rds_host={catalog.rds_host}")

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
            "bucket": catalog.s3_bucket,
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


@sensor(
    name="duckling_backfill_discovery_sensor",
    minimum_interval_seconds=3600,  # Run hourly
)
def duckling_backfill_discovery_sensor(context: SensorEvaluationContext) -> SensorResult:
    """Discover teams with DuckLakeCatalog entries and create daily backfill partitions.

    This sensor runs periodically to:
    1. Find all teams with DuckLakeCatalog configurations
    2. Create partitions for yesterday's data (if not already exists)
    3. Trigger backfill runs for new partitions
    """
    # Import here to avoid Django setup issues at module load time
    from posthog.ducklake.models import DuckLakeCatalog

    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Get existing partitions
    existing = set(context.instance.get_dynamic_partitions("duckling_events_backfill"))

    new_partitions: list[str] = []
    run_requests: list[RunRequest] = []

    # Find all teams with duckling configurations
    for catalog in DuckLakeCatalog.objects.all():
        partition_key = f"{catalog.team_id}_{yesterday}"

        if partition_key not in existing:
            new_partitions.append(partition_key)
            run_requests.append(
                RunRequest(
                    partition_key=partition_key,
                    run_key=partition_key,
                )
            )
            context.log.info(f"Creating partition for team_id={catalog.team_id}, date={yesterday}")

    if new_partitions:
        context.log.info(f"Discovered {len(new_partitions)} new partitions to backfill")
        logger.info(
            "duckling_sensor_discovered_partitions",
            count=len(new_partitions),
            partitions=new_partitions,
        )

    return SensorResult(
        run_requests=run_requests,
        dynamic_partitions_requests=[duckling_backfill_partitions_def.build_add_request(new_partitions)]
        if new_partitions
        else [],
    )


duckling_events_backfill_job = define_asset_job(
    name="duckling_events_backfill_job",
    selection=["duckling_events_backfill"],
    tags={
        "owner": JobOwners.TEAM_DATA_STACK.value,
        "disable_slack_notifications": True,
        **CONCURRENCY_TAG,
    },
)
