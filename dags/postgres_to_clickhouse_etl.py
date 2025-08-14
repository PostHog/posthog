"""ETL pipeline for syncing posthog_organization and posthog_team tables from Postgres to ClickHouse."""

import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from typing import Any, Optional
from dataclasses import dataclass
import json

import dagster
from django.conf import settings
from dagster import (
    AssetExecutionContext,
    Config,
    HourlyPartitionsDefinition,
    MetadataValue,
    OpExecutionContext,
    RetryPolicy,
    ScheduleDefinition,
    asset,
    job,
    op,
)
from dagster._core.definitions.backfill_policy import BackfillPolicy

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from dags.common import JobOwners


class PostgresToClickHouseETLConfig(Config):
    """Configuration for the Postgres to ClickHouse ETL job."""

    full_refresh: bool = False
    batch_size: int = 10000
    max_execution_time: int = 3600


@dataclass
class ETLState:
    """Track the state of the ETL process."""

    last_sync_timestamp: Optional[datetime] = None
    rows_synced: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


# Define retry policy for transient failures
etl_retry_policy = RetryPolicy(
    max_retries=3,
    delay=60,
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.PLUS_MINUS,
)


def get_postgres_connection():
    """Get a connection to the Postgres database."""
    return psycopg2.connect(
        host=settings.DATABASE_HOST,
        port=settings.DATABASE_PORT,
        database=settings.DATABASE_NAME,
        user=settings.DATABASE_USER,
        password=settings.DATABASE_PASSWORD,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def get_organization_table_sql() -> str:
    """Get SQL for creating the organization table."""
    return """
        CREATE TABLE IF NOT EXISTS models.posthog_organization (
            id Int64,
            uuid UUID,
            name String,
            slug String,
            logo_media_id Nullable(Int64),
            created_at DateTime64(6),
            updated_at DateTime64(6),
            session_cookie_age Nullable(Int32),
            is_member_join_email_enabled UInt8,
            is_ai_data_processing_approved Nullable(UInt8),
            enforce_2fa Nullable(UInt8),
            members_can_invite Nullable(UInt8),
            members_can_use_personal_api_keys UInt8,
            allow_publicly_shared_resources UInt8,
            plugins_access_level Int16,
            for_internal_metrics UInt8,
            default_experiment_stats_method Nullable(String),
            is_hipaa Nullable(UInt8),
            customer_id Nullable(String),
            available_product_features Nullable(String),  -- JSON stored as String
            usage Nullable(String),  -- JSON stored as String
            never_drop_data Nullable(UInt8),
            customer_trust_scores Nullable(String),  -- JSON stored as String
            setup_section_2_completed UInt8,
            personalization String,  -- JSON stored as String
            domain_whitelist Array(String),
            is_platform Nullable(UInt8),
            _inserted_at DateTime64(6) DEFAULT now64(6)
        )
        ENGINE = ReplacingMergeTree(_inserted_at)
        ORDER BY (id, updated_at)
        SETTINGS index_granularity = 8192
    """


def get_team_table_sql() -> str:
    """Get SQL for creating the team table."""
    return """
        CREATE TABLE IF NOT EXISTS models.posthog_team (
            id Int64,
            uuid UUID,
            organization_id Int64,
            parent_team_id Nullable(Int64),
            project_id Int64,
            api_token String,
            app_urls Array(String),
            name String,
            slack_incoming_webhook Nullable(String),
            created_at DateTime64(6),
            updated_at DateTime64(6),
            anonymize_ips UInt8,
            completed_snippet_onboarding UInt8,
            has_completed_onboarding_for Nullable(String),  -- JSON stored as String
            onboarding_tasks Nullable(String),  -- JSON stored as String
            ingested_event UInt8,
            autocapture_opt_out Nullable(UInt8),
            autocapture_web_vitals_opt_in Nullable(UInt8),
            autocapture_web_vitals_allowed_metrics Nullable(String),  -- JSON stored as String
            autocapture_exceptions_opt_in Nullable(UInt8),
            autocapture_exceptions_errors_to_ignore Nullable(String),  -- JSON stored as String
            person_processing_opt_out Nullable(UInt8),
            secret_api_token Nullable(String),
            secret_api_token_backup Nullable(String),
            session_recording_opt_in UInt8,
            session_recording_sample_rate Nullable(Decimal(3, 2)),
            session_recording_minimum_duration_milliseconds Nullable(Int32),
            session_recording_linked_flag Nullable(String),  -- JSON stored as String
            session_recording_network_payload_capture_config Nullable(String),  -- JSON stored as String
            session_recording_masking_config Nullable(String),  -- JSON stored as String
            session_recording_url_trigger_config Nullable(String),  -- JSON stored as String
            session_recording_url_blocklist_config Nullable(String),  -- JSON stored as String
            session_recording_event_trigger_config Nullable(String),  -- JSON stored as String
            session_recording_trigger_match_type_config Nullable(String),
            session_replay_config Nullable(String),  -- JSON stored as String
            survey_config Nullable(String),  -- JSON stored as String
            capture_console_log_opt_in Nullable(UInt8),
            capture_performance_opt_in Nullable(UInt8),
            capture_dead_clicks Nullable(UInt8),
            surveys_opt_in Nullable(UInt8),
            heatmaps_opt_in Nullable(UInt8),
            flags_persistence_default Nullable(UInt8),
            feature_flag_confirmation_enabled Nullable(UInt8),
            feature_flag_confirmation_message Nullable(String),
            session_recording_version Nullable(String),
            signup_token Nullable(String),
            is_demo UInt8,
            access_control UInt8,
            week_start_day Nullable(Int8),
            inject_web_apps Nullable(UInt8),
            test_account_filters String,  -- JSON stored as String
            test_account_filters_default_checked Nullable(UInt8),
            path_cleaning_filters Nullable(String),  -- JSON stored as String
            timezone String,
            data_attributes String,  -- JSON stored as String
            person_display_name_properties Array(String),
            live_events_columns Array(String),
            recording_domains Array(String),
            human_friendly_comparison_periods Nullable(UInt8),
            cookieless_server_hash_mode Nullable(Int8),
            primary_dashboard_id Nullable(Int64),
            default_data_theme Nullable(Int32),
            extra_settings Nullable(String),  -- JSON stored as String
            modifiers Nullable(String),  -- JSON stored as String
            correlation_config Nullable(String),  -- JSON stored as String
            session_recording_retention_period_days Nullable(Int32),
            plugins_opt_in UInt8,
            opt_out_capture UInt8,
            event_names String,  -- JSON stored as String
            event_names_with_usage String,  -- JSON stored as String
            event_properties String,  -- JSON stored as String
            event_properties_with_usage String,  -- JSON stored as String
            event_properties_numerical String,  -- JSON stored as String
            external_data_workspace_id Nullable(String),
            external_data_workspace_last_synced_at Nullable(DateTime64(6)),
            api_query_rate_limit Nullable(String),
            revenue_tracking_config Nullable(String),  -- JSON stored as String
            drop_events_older_than Nullable(Int64),  -- Store duration as seconds
            base_currency Nullable(String),
            _inserted_at DateTime64(6) DEFAULT now64(6)
        )
        ENGINE = ReplacingMergeTree(_inserted_at)
        ORDER BY (organization_id, id, updated_at)
        SETTINGS index_granularity = 8192
    """


def create_clickhouse_tables() -> None:
    """Create the organization and team tables in ClickHouse on all nodes."""
    # Create tables on all nodes
    run_sql_with_exceptions(get_organization_table_sql(), node_role=NodeRole.ALL)
    run_sql_with_exceptions(get_team_table_sql(), node_role=NodeRole.ALL)


def fetch_organizations(conn, last_sync: Optional[datetime] = None, batch_size: int = 10000) -> list[dict]:
    """Fetch organizations from Postgres."""
    cursor = conn.cursor()

    query = """
        SELECT
            id,
            uuid,
            name,
            slug,
            logo_media_id,
            created_at,
            updated_at,
            session_cookie_age,
            is_member_join_email_enabled,
            is_ai_data_processing_approved,
            enforce_2fa,
            members_can_invite,
            members_can_use_personal_api_keys,
            allow_publicly_shared_resources,
            plugins_access_level,
            for_internal_metrics,
            default_experiment_stats_method,
            is_hipaa,
            customer_id,
            available_product_features,
            usage,
            never_drop_data,
            customer_trust_scores,
            setup_section_2_completed,
            personalization,
            domain_whitelist,
            is_platform
        FROM posthog_organization
    """

    params = []
    if last_sync:
        query += " WHERE updated_at > %s"
        params.append(last_sync)

    query += " ORDER BY updated_at ASC"

    cursor.execute(query, params)

    rows = []
    while True:
        batch = cursor.fetchmany(batch_size)
        if not batch:
            break
        rows.extend(batch)

    cursor.close()
    return rows


def fetch_teams(conn, last_sync: Optional[datetime] = None, batch_size: int = 10000) -> list[dict]:
    """Fetch teams from Postgres."""
    cursor = conn.cursor()

    query = """
        SELECT
            id,
            uuid,
            organization_id,
            parent_team_id,
            project_id,
            api_token,
            app_urls,
            name,
            slack_incoming_webhook,
            created_at,
            updated_at,
            anonymize_ips,
            completed_snippet_onboarding,
            has_completed_onboarding_for,
            onboarding_tasks,
            ingested_event,
            autocapture_opt_out,
            autocapture_web_vitals_opt_in,
            autocapture_web_vitals_allowed_metrics,
            autocapture_exceptions_opt_in,
            autocapture_exceptions_errors_to_ignore,
            person_processing_opt_out,
            secret_api_token,
            secret_api_token_backup,
            session_recording_opt_in,
            session_recording_sample_rate,
            session_recording_minimum_duration_milliseconds,
            session_recording_linked_flag,
            session_recording_network_payload_capture_config,
            session_recording_masking_config,
            session_recording_url_trigger_config,
            session_recording_url_blocklist_config,
            session_recording_event_trigger_config,
            session_recording_trigger_match_type_config,
            session_replay_config,
            survey_config,
            capture_console_log_opt_in,
            capture_performance_opt_in,
            capture_dead_clicks,
            surveys_opt_in,
            heatmaps_opt_in,
            flags_persistence_default,
            feature_flag_confirmation_enabled,
            feature_flag_confirmation_message,
            session_recording_version,
            signup_token,
            is_demo,
            access_control,
            week_start_day,
            inject_web_apps,
            test_account_filters,
            test_account_filters_default_checked,
            path_cleaning_filters,
            timezone,
            data_attributes,
            person_display_name_properties,
            live_events_columns,
            recording_domains,
            human_friendly_comparison_periods,
            cookieless_server_hash_mode,
            primary_dashboard_id,
            default_data_theme,
            extra_settings,
            modifiers,
            correlation_config,
            session_recording_retention_period_days,
            plugins_opt_in,
            opt_out_capture,
            event_names,
            event_names_with_usage,
            event_properties,
            event_properties_with_usage,
            event_properties_numerical,
            external_data_workspace_id,
            external_data_workspace_last_synced_at,
            api_query_rate_limit,
            revenue_tracking_config,
            drop_events_older_than,
            base_currency
        FROM posthog_team
    """

    params = []
    if last_sync:
        query += " WHERE updated_at > %s"
        params.append(last_sync)

    query += " ORDER BY updated_at ASC"

    cursor.execute(query, params)

    rows = []
    while True:
        batch = cursor.fetchmany(batch_size)
        if not batch:
            break
        rows.extend(batch)

    cursor.close()
    return rows


def transform_organization_row(row: dict) -> dict:
    """Transform a Postgres organization row for ClickHouse insertion."""
    # Convert JSON fields to strings
    json_fields = ["available_product_features", "usage", "customer_trust_scores", "personalization"]

    for field in json_fields:
        if row.get(field) is not None:
            row[field] = json.dumps(row[field])

    # Convert boolean fields to UInt8
    bool_fields = [
        "is_member_join_email_enabled",
        "is_ai_data_processing_approved",
        "enforce_2fa",
        "members_can_invite",
        "members_can_use_personal_api_keys",
        "allow_publicly_shared_resources",
        "for_internal_metrics",
        "is_hipaa",
        "never_drop_data",
        "setup_section_2_completed",
        "is_platform",
    ]

    for field in bool_fields:
        if row.get(field) is not None:
            row[field] = 1 if row[field] else 0

    return row


def transform_team_row(row: dict) -> dict:
    """Transform a Postgres team row for ClickHouse insertion."""
    # Convert JSON fields to strings
    json_fields = [
        "has_completed_onboarding_for",
        "onboarding_tasks",
        "autocapture_web_vitals_allowed_metrics",
        "autocapture_exceptions_errors_to_ignore",
        "session_recording_linked_flag",
        "session_recording_network_payload_capture_config",
        "session_recording_masking_config",
        "session_recording_url_trigger_config",
        "session_recording_url_blocklist_config",
        "session_recording_event_trigger_config",
        "session_replay_config",
        "survey_config",
        "test_account_filters",
        "path_cleaning_filters",
        "data_attributes",
        "extra_settings",
        "modifiers",
        "correlation_config",
        "event_names",
        "event_names_with_usage",
        "event_properties",
        "event_properties_with_usage",
        "event_properties_numerical",
        "revenue_tracking_config",
    ]

    for field in json_fields:
        if row.get(field) is not None:
            row[field] = json.dumps(row[field])

    # Convert boolean fields to UInt8
    bool_fields = [
        "anonymize_ips",
        "completed_snippet_onboarding",
        "ingested_event",
        "autocapture_opt_out",
        "autocapture_web_vitals_opt_in",
        "autocapture_exceptions_opt_in",
        "person_processing_opt_out",
        "session_recording_opt_in",
        "capture_console_log_opt_in",
        "capture_performance_opt_in",
        "capture_dead_clicks",
        "surveys_opt_in",
        "heatmaps_opt_in",
        "flags_persistence_default",
        "feature_flag_confirmation_enabled",
        "is_demo",
        "access_control",
        "inject_web_apps",
        "test_account_filters_default_checked",
        "human_friendly_comparison_periods",
        "plugins_opt_in",
        "opt_out_capture",
    ]

    for field in bool_fields:
        if row.get(field) is not None:
            row[field] = 1 if row[field] else 0

    # Convert timedelta to seconds
    if row.get("drop_events_older_than") is not None:
        row["drop_events_older_than"] = int(row["drop_events_older_than"].total_seconds())

    # Handle array fields that might be None
    array_fields = ["app_urls", "person_display_name_properties", "live_events_columns", "recording_domains"]
    for field in array_fields:
        if row.get(field) is None:
            row[field] = []

    return row


def insert_organizations_to_clickhouse(organizations: list[dict], batch_size: int = 10000) -> int:
    """Insert organizations into ClickHouse."""
    if not organizations:
        return 0

    # Transform the data
    transformed = [transform_organization_row(org) for org in organizations]

    # Prepare data for insertion
    columns = list(transformed[0].keys())

    # Insert in batches
    total_inserted = 0
    for i in range(0, len(transformed), batch_size):
        batch = transformed[i : i + batch_size]

        # Build parameterized query
        placeholders = ", ".join([f"({', '.join(['%s'] * len(columns))})" for _ in batch])
        query = f"INSERT INTO models.posthog_organization ({', '.join(columns)}) VALUES {placeholders}"

        # Flatten values for parameterized query
        values = []
        for row in batch:
            for col in columns:
                values.append(row.get(col))

        sync_execute(query, values)
        total_inserted += len(batch)

    return total_inserted


def insert_teams_to_clickhouse(teams: list[dict], batch_size: int = 10000) -> int:
    """Insert teams into ClickHouse."""
    if not teams:
        return 0

    # Transform the data
    transformed = [transform_team_row(team) for team in teams]

    # Prepare data for insertion
    columns = list(transformed[0].keys())

    # Insert in batches
    total_inserted = 0
    for i in range(0, len(transformed), batch_size):
        batch = transformed[i : i + batch_size]

        # Build parameterized query
        placeholders = ", ".join([f"({', '.join(['%s'] * len(columns))})" for _ in batch])
        query = f"INSERT INTO models.posthog_team ({', '.join(columns)}) VALUES {placeholders}"

        # Flatten values for parameterized query
        values = []
        for row in batch:
            for col in columns:
                values.append(row.get(col))

        sync_execute(query, values)
        total_inserted += len(batch)

    return total_inserted


@op(retry_policy=etl_retry_policy)
def sync_organizations(
    context: OpExecutionContext,
    config: PostgresToClickHouseETLConfig,
) -> ETLState:
    """Sync organizations from Postgres to ClickHouse."""
    state = ETLState()

    # Create tables if they don't exist
    create_clickhouse_tables()

    # Get last sync timestamp from ClickHouse (if incremental)
    last_sync = None
    if not config.full_refresh:
        result = sync_execute("SELECT max(updated_at) FROM models.posthog_organization")
        if result and result[0][0]:
            last_sync = result[0][0]
            context.log.info(f"Last sync timestamp for organizations: {last_sync}")

    # If full refresh, truncate the table
    if config.full_refresh:
        sync_execute("TRUNCATE TABLE models.posthog_organization")
        context.log.info("Truncated posthog_organization table for full refresh")

    # Connect to Postgres and fetch data
    pg_conn = get_postgres_connection()
    try:
        organizations = fetch_organizations(pg_conn, last_sync=last_sync, batch_size=config.batch_size)
        context.log.info(f"Fetched {len(organizations)} organizations from Postgres")

        # Insert into ClickHouse
        if organizations:
            rows_inserted = insert_organizations_to_clickhouse(organizations, batch_size=config.batch_size)
            state.rows_synced = rows_inserted
            state.last_sync_timestamp = max(org["updated_at"] for org in organizations)
            context.log.info(f"Inserted {rows_inserted} organizations into ClickHouse")

    except Exception as e:
        state.errors.append(f"Error syncing organizations: {str(e)}")
        context.log.exception(f"Error syncing organizations: {str(e)}")
        raise
    finally:
        pg_conn.close()

    # Add metadata
    context.add_output_metadata(
        {
            "rows_synced": MetadataValue.int(state.rows_synced),
            "last_sync_timestamp": MetadataValue.text(
                str(state.last_sync_timestamp) if state.last_sync_timestamp else "N/A"
            ),
            "full_refresh": MetadataValue.bool(config.full_refresh),
        }
    )

    return state


@op(retry_policy=etl_retry_policy)
def sync_teams(
    context: OpExecutionContext,
    config: PostgresToClickHouseETLConfig,
) -> ETLState:
    """Sync teams from Postgres to ClickHouse."""
    state = ETLState()

    # Create tables if they don't exist
    create_clickhouse_tables()

    # Get last sync timestamp from ClickHouse (if incremental)
    last_sync = None
    if not config.full_refresh:
        result = sync_execute("SELECT max(updated_at) FROM models.posthog_team")
        if result and result[0][0]:
            last_sync = result[0][0]
            context.log.info(f"Last sync timestamp for teams: {last_sync}")

    # If full refresh, truncate the table
    if config.full_refresh:
        sync_execute("TRUNCATE TABLE models.posthog_team")
        context.log.info("Truncated posthog_team table for full refresh")

    # Connect to Postgres and fetch data
    pg_conn = get_postgres_connection()
    try:
        teams = fetch_teams(pg_conn, last_sync=last_sync, batch_size=config.batch_size)
        context.log.info(f"Fetched {len(teams)} teams from Postgres")

        # Insert into ClickHouse
        if teams:
            rows_inserted = insert_teams_to_clickhouse(teams, batch_size=config.batch_size)
            state.rows_synced = rows_inserted
            state.last_sync_timestamp = max(team["updated_at"] for team in teams)
            context.log.info(f"Inserted {rows_inserted} teams into ClickHouse")

    except Exception as e:
        state.errors.append(f"Error syncing teams: {str(e)}")
        context.log.exception(f"Error syncing teams: {str(e)}")
        raise
    finally:
        pg_conn.close()

    # Add metadata
    context.add_output_metadata(
        {
            "rows_synced": MetadataValue.int(state.rows_synced),
            "last_sync_timestamp": MetadataValue.text(
                str(state.last_sync_timestamp) if state.last_sync_timestamp else "N/A"
            ),
            "full_refresh": MetadataValue.bool(config.full_refresh),
        }
    )

    return state


@op
def verify_sync(
    context: OpExecutionContext,
    org_state: ETLState,
    team_state: ETLState,
) -> dict[str, Any]:
    """Verify the sync was successful by checking row counts."""
    # Get counts from ClickHouse
    org_count_result = sync_execute("SELECT count(*) FROM models.posthog_organization")
    team_count_result = sync_execute("SELECT count(*) FROM models.posthog_team")

    org_count = org_count_result[0][0] if org_count_result else 0
    team_count = team_count_result[0][0] if team_count_result else 0

    verification = {
        "organizations": {
            "clickhouse_count": org_count,
            "rows_synced": org_state.rows_synced,
            "last_sync": str(org_state.last_sync_timestamp) if org_state.last_sync_timestamp else None,
        },
        "teams": {
            "clickhouse_count": team_count,
            "rows_synced": team_state.rows_synced,
            "last_sync": str(team_state.last_sync_timestamp) if team_state.last_sync_timestamp else None,
        },
        "success": len(org_state.errors) == 0 and len(team_state.errors) == 0,
    }

    context.log.info(f"Verification results: {verification}")

    context.add_output_metadata(
        {
            "org_count": MetadataValue.int(org_count),
            "team_count": MetadataValue.int(team_count),
            "success": MetadataValue.bool(verification["success"]),
        }
    )

    return verification


# Define the hourly partition
hourly_partition = HourlyPartitionsDefinition(
    start_date="2024-01-01-00:00",
    timezone="UTC",
)


@job(
    tags={"owner": JobOwners.TEAM_CLICKHOUSE.value},
    partitions_def=hourly_partition,
)
def postgres_to_clickhouse_etl_job():
    """Hourly ETL job to sync organization and team data from Postgres to ClickHouse."""
    org_state = sync_organizations()
    team_state = sync_teams()
    verify_sync(org_state, team_state)


# Asset-based approach (alternative/additional to ops)
@asset(
    retry_policy=etl_retry_policy,
    partitions_def=hourly_partition,
    backfill_policy=BackfillPolicy(max_partitions_per_run=24),  # Allow up to 24 hours backfill at once
)
def organizations_in_clickhouse(
    context: AssetExecutionContext,
) -> None:
    """Asset representing organizations data in ClickHouse."""
    config = PostgresToClickHouseETLConfig(full_refresh=False)

    # Create tables if they don't exist
    create_clickhouse_tables()

    # Determine the time window for this partition
    partition_key = context.partition_key
    # Hourly partition key format: "2024-01-01-14:00"
    partition_datetime = datetime.strptime(partition_key, "%Y-%m-%d-%H:%M")
    start_time = partition_datetime
    end_time = partition_datetime + timedelta(hours=1)

    # Connect to Postgres and fetch data for this partition
    pg_conn = get_postgres_connection()
    try:
        cursor = pg_conn.cursor()
        cursor.execute(
            """
            SELECT
                id,
                uuid,
                name,
                slug,
                logo_media_id,
                created_at,
                updated_at,
                session_cookie_age,
                is_member_join_email_enabled,
                is_ai_data_processing_approved,
                enforce_2fa,
                members_can_invite,
                members_can_use_personal_api_keys,
                allow_publicly_shared_resources,
                plugins_access_level,
                for_internal_metrics,
                default_experiment_stats_method,
                is_hipaa,
                customer_id,
                available_product_features,
                usage,
                never_drop_data,
                customer_trust_scores,
                setup_section_2_completed,
                personalization,
                domain_whitelist,
                is_platform
            FROM posthog_organization
            WHERE updated_at >= %s AND updated_at < %s
            ORDER BY updated_at ASC
            """,
            (start_time, end_time),
        )

        organizations = cursor.fetchall()
        context.log.info(f"Fetched {len(organizations)} organizations for partition {partition_key}")

        # Insert into ClickHouse
        if organizations:
            rows_inserted = insert_organizations_to_clickhouse(organizations, batch_size=config.batch_size)
            context.log.info(f"Inserted {rows_inserted} organizations into ClickHouse")

        cursor.close()

    finally:
        pg_conn.close()


@asset(
    retry_policy=etl_retry_policy,
    partitions_def=hourly_partition,
    backfill_policy=BackfillPolicy(max_partitions_per_run=24),  # Allow up to 24 hours backfill at once
)
def teams_in_clickhouse(
    context: AssetExecutionContext,
) -> None:
    """Asset representing teams data in ClickHouse."""
    config = PostgresToClickHouseETLConfig(full_refresh=False)

    # Create tables if they don't exist
    create_clickhouse_tables()

    # Determine the time window for this partition
    partition_key = context.partition_key
    # Hourly partition key format: "2024-01-01-14:00"
    partition_datetime = datetime.strptime(partition_key, "%Y-%m-%d-%H:%M")
    start_time = partition_datetime
    end_time = partition_datetime + timedelta(hours=1)

    # Connect to Postgres and fetch data for this partition
    pg_conn = get_postgres_connection()
    try:
        cursor = pg_conn.cursor()
        cursor.execute(
            """
            SELECT
                id,
                uuid,
                organization_id,
                parent_team_id,
                project_id,
                api_token,
                app_urls,
                name,
                slack_incoming_webhook,
                created_at,
                updated_at,
                anonymize_ips,
                completed_snippet_onboarding,
                has_completed_onboarding_for,
                onboarding_tasks,
                ingested_event,
                autocapture_opt_out,
                autocapture_web_vitals_opt_in,
                autocapture_web_vitals_allowed_metrics,
                autocapture_exceptions_opt_in,
                autocapture_exceptions_errors_to_ignore,
                person_processing_opt_out,
                secret_api_token,
                secret_api_token_backup,
                session_recording_opt_in,
                session_recording_sample_rate,
                session_recording_minimum_duration_milliseconds,
                session_recording_linked_flag,
                session_recording_network_payload_capture_config,
                session_recording_masking_config,
                session_recording_url_trigger_config,
                session_recording_url_blocklist_config,
                session_recording_event_trigger_config,
                session_recording_trigger_match_type_config,
                session_replay_config,
                survey_config,
                capture_console_log_opt_in,
                capture_performance_opt_in,
                capture_dead_clicks,
                surveys_opt_in,
                heatmaps_opt_in,
                flags_persistence_default,
                feature_flag_confirmation_enabled,
                feature_flag_confirmation_message,
                session_recording_version,
                signup_token,
                is_demo,
                access_control,
                week_start_day,
                inject_web_apps,
                test_account_filters,
                test_account_filters_default_checked,
                path_cleaning_filters,
                timezone,
                data_attributes,
                person_display_name_properties,
                live_events_columns,
                recording_domains,
                human_friendly_comparison_periods,
                cookieless_server_hash_mode,
                primary_dashboard_id,
                default_data_theme,
                extra_settings,
                modifiers,
                correlation_config,
                session_recording_retention_period_days,
                plugins_opt_in,
                opt_out_capture,
                event_names,
                event_names_with_usage,
                event_properties,
                event_properties_with_usage,
                event_properties_numerical,
                external_data_workspace_id,
                external_data_workspace_last_synced_at,
                api_query_rate_limit,
                revenue_tracking_config,
                drop_events_older_than,
                base_currency
            FROM posthog_team
            WHERE updated_at >= %s AND updated_at < %s
            ORDER BY updated_at ASC
            """,
            (start_time, end_time),
        )

        teams = cursor.fetchall()
        context.log.info(f"Fetched {len(teams)} teams for partition {partition_key}")

        # Insert into ClickHouse
        if teams:
            rows_inserted = insert_teams_to_clickhouse(teams, batch_size=config.batch_size)
            context.log.info(f"Inserted {rows_inserted} teams into ClickHouse")

        cursor.close()

    finally:
        pg_conn.close()


# Create an hourly schedule for the job
postgres_to_clickhouse_hourly_schedule = ScheduleDefinition(
    job=postgres_to_clickhouse_etl_job,
    cron_schedule="0 * * * *",  # Run at the top of every hour
    name="postgres_to_clickhouse_hourly",
    execution_timezone="UTC",
)
