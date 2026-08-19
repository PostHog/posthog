"""ETL pipeline for syncing posthog_organization, posthog_team, and posthog_featureflag from Postgres to ClickHouse.

Table-driven so watermark handling, batching, and column selection live in one place. Adding a table
means a TableConfig entry plus DDL; sync comes free.

How correctness is shared with the storage engine:
- Incremental windows overlap by ``backward_lookback_seconds`` so a row committed after its
  timestamp slot passed the prior high-watermark is still picked up next run.
- Re-emitted rows inside that overlap are deduped by the ReplicatedReplacingMergeTree engine at
  merge time (``_inserted_at`` as the version column). Readers of the mirror use FINAL / argMax,
  as every other ClickHouse consumer of these tables already must.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, Union

from django.conf import settings

import dagster
import psycopg2
import psycopg2.extras
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
from posthog.clickhouse.cluster import Query, get_cluster
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dags.common import JobOwners
from posthog.dataclasses import frozen

PostgresFilter = Callable[[Optional[datetime]], tuple[str, list[Any]]]


@frozen
class TableConfig:
    """Declarative description of one Postgres→ClickHouse mirror.

    - ``key``: columns that identify a row across writes. Must be immutable for the life of the row
      so a soft-delete-rename (feature flags rename ``key`` on tombstone) lands as an update, not a
      new identity. The same key drives the ClickHouse ORDER BY prefix.
    - ``watermark_column``: the non-null change-timestamp column mirrored in ClickHouse and used
      to advance the incremental high-watermark. The transform is responsible for never emitting
      a NULL here (feature flags fall back to ``created_at``).
    - ``postgres_filter``: builds the incremental WHERE clause and params for the Postgres read;
      lets one table (feature flags' nullable ``updated_at``) deviate without leaking that quirk
      into the generic runner.
    - ``order_by``: full ClickHouse ORDER BY tuple. Contains ``key`` (optionally behind a leading
      locality column such as ``organization_id`` for teams) so same-row versions land in the same
      part; ends with ``watermark_column`` so ``argMax`` reads are cheap.
    - ``projections``: derived columns computed from the raw Postgres row before load (flag
      dependency / cohort / variant counts for Grafana aggregation).
    """

    key: tuple[str, ...]
    watermark_column: str
    order_by: str
    projections: dict[str, Callable[[dict[str, Any]], Any]]
    postgres_filter: Optional[PostgresFilter] = None


@dataclass
class IncrementalState:
    last_sync_timestamp: Optional[datetime] = None
    rows_synced: int = 0


def _feature_flag_postgres_filter(last_sync: Optional[datetime]) -> tuple[str, list[Any]]:
    # updated_at is NULL until a flag's first edit; take rows where either column moved into the window.
    if last_sync is None:
        return "", []
    return "WHERE (updated_at > %s OR (updated_at IS NULL AND created_at > %s))", [last_sync, last_sync]


def _has_flag_dependency(filters: dict[str, Any]) -> int:
    # A dependency is a property with type "flag" inside filters.groups; there is no top-level
    # flag_dependencies key (see _extract_direct_dependency_ids in products/feature_flags).
    for group in filters.get("groups") or []:
        if not isinstance(group, dict):
            continue
        if any(isinstance(p, dict) and p.get("type") == "flag" for p in group.get("properties") or []):
            return 1
    return 0


def _has_cohort_filters(filters: dict[str, Any]) -> int:
    for group in filters.get("groups") or []:
        if not isinstance(group, dict):
            continue
        if any(isinstance(p, dict) and p.get("type") == "cohort" for p in group.get("properties") or []):
            return 1
    return 0


def _variant_count(filters: dict[str, Any]) -> int:
    multivariate = filters.get("multivariate")
    variants = multivariate.get("variants") if isinstance(multivariate, dict) else None
    return len(variants) if isinstance(variants, list) else 0


TABLE_CONFIGS: dict[str, TableConfig] = {
    "posthog_organization": TableConfig(
        key=("id",),
        watermark_column="updated_at",
        order_by="(id, updated_at)",
        projections={},
    ),
    "posthog_team": TableConfig(
        key=("id",),
        watermark_column="updated_at",
        order_by="(organization_id, id, updated_at)",
        projections={},
    ),
    # Identity is (team_id, id), not (team_id, key): soft-delete renames key with a :deleted:<id>
    # suffix, and id is what survives that rename. updated_at is the watermark; the transform
    # backfills NULLs from created_at so the mirror never stores NULL.
    "posthog_featureflag": TableConfig(
        key=("team_id", "id"),
        watermark_column="updated_at",
        order_by="(team_id, id, updated_at)",
        projections={
            "has_flag_dependency": _has_flag_dependency,
            "has_cohort_filters": _has_cohort_filters,
            "variant_count": _variant_count,
        },
        postgres_filter=_feature_flag_postgres_filter,
    ),
}


class PostgresToClickHouseETLConfig(Config):
    full_refresh: bool = False
    batch_size: int = 10000
    # Overlap the incremental window by this much to catch rows that committed after their
    # timestamp slot passed the prior high-watermark. The engine dedupes the overlap at merge time.
    backward_lookback_seconds: int = 86400


etl_retry_policy = RetryPolicy(
    max_retries=3,
    delay=60,
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.PLUS_MINUS,
)


def get_postgres_connection():
    db_config = settings.DATABASES["default"]
    return psycopg2.connect(
        host=db_config["HOST"],
        port=db_config["PORT"],
        database=db_config["NAME"],
        user=db_config["USER"],
        password=db_config["PASSWORD"],
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def get_organization_table_sql() -> str:
    return """
        CREATE TABLE IF NOT EXISTS models.posthog_organization (
            id UUID,
            name String,
            slug String,
            logo_media_id Nullable(UUID),
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
        ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog_organization', '{shard}-{replica}', _inserted_at)
        ORDER BY (id, updated_at)
        SETTINGS index_granularity = 8192
    """


def get_team_table_sql() -> str:
    return """
        CREATE TABLE IF NOT EXISTS models.posthog_team (
            id Int64,
            uuid UUID,
            organization_id UUID,
            parent_team_id Nullable(Int64),
            project_id Int64,
            api_token String,
            app_urls Array(String),
            name String,
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
            drop_events_older_than Nullable(Int64),
            base_currency Nullable(String),
            _inserted_at DateTime64(6) DEFAULT now64(6)
        )
        ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog_team', '{shard}-{replica}', _inserted_at)
        ORDER BY (organization_id, id, updated_at)
        SETTINGS index_granularity = 8192
    """


def get_feature_flag_table_sql() -> str:
    order_by = TABLE_CONFIGS["posthog_featureflag"].order_by
    projection_columns = ", ".join(f"{name} UInt32" for name in TABLE_CONFIGS["posthog_featureflag"].projections)
    return f"""
        CREATE TABLE IF NOT EXISTS models.posthog_featureflag (
            id Int64,
            team_id Int64,
            key String,
            name String,
            filters String,  -- JSON serialized
            deleted UInt8,
            active UInt8,
            archived UInt8,
            version Nullable(Int32),
            ensure_experience_continuity Nullable(UInt8),
            usage_dashboard_id Nullable(Int64),
            has_enriched_analytics Nullable(UInt8),
            is_remote_configuration Nullable(UInt8),
            has_encrypted_payloads Nullable(UInt8),
            evaluation_runtime Nullable(String),
            bucketing_identifier Nullable(String),
            created_by_id Nullable(Int32),
            created_at DateTime64(6),
            updated_at DateTime64(6),
            {projection_columns},
            _inserted_at DateTime64(6) DEFAULT now64(6)
        )
        ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog_featureflag', '{{shard}}-{{replica}}', _inserted_at)
        ORDER BY {order_by}
        SETTINGS index_granularity = 8192
    """


DDL_BY_TABLE: dict[str, Callable[[], str]] = {
    "posthog_organization": get_organization_table_sql,
    "posthog_team": get_team_table_sql,
    "posthog_featureflag": get_feature_flag_table_sql,
}


def create_database_if_not_exists(context: Optional[Union[OpExecutionContext, AssetExecutionContext]] = None) -> None:
    if context:
        context.log.info("Creating database 'models' if it doesn't exist...")
    cluster = get_cluster()
    cluster.map_all_hosts(Query("CREATE DATABASE IF NOT EXISTS models")).result()


def create_clickhouse_tables(
    context: Optional[Union[OpExecutionContext, AssetExecutionContext]] = None, force_recreate: bool = False
) -> None:
    create_database_if_not_exists(context)
    cluster = get_cluster()
    if force_recreate:
        for table_name in TABLE_CONFIGS:
            cluster.map_all_hosts(Query(f"DROP TABLE IF EXISTS models.{table_name}")).result()
    for table_name, ddl_fn in DDL_BY_TABLE.items():
        if context:
            context.log.info(f"Creating models.{table_name} if it doesn't exist...")
        cluster.map_all_hosts(Query(ddl_fn())).result()


# Organized per table rather than per kind because no two tables share a kind combination.
_ORG_COLS = [
    "id",
    "name",
    "slug",
    "logo_media_id",
    "created_at",
    "updated_at",
    "session_cookie_age",
    "is_member_join_email_enabled",
    "is_ai_data_processing_approved",
    "enforce_2fa",
    "members_can_invite",
    "members_can_use_personal_api_keys",
    "allow_publicly_shared_resources",
    "plugins_access_level",
    "for_internal_metrics",
    "default_experiment_stats_method",
    "is_hipaa",
    "customer_id",
    "available_product_features",
    "usage",
    "never_drop_data",
    "customer_trust_scores",
    "setup_section_2_completed",
    "personalization",
    "domain_whitelist",
    "is_platform",
]

_TEAM_COLS = [
    "id",
    "uuid",
    "organization_id",
    "parent_team_id",
    "project_id",
    "api_token",
    "app_urls",
    "name",
    "created_at",
    "updated_at",
    "anonymize_ips",
    "completed_snippet_onboarding",
    "has_completed_onboarding_for",
    "onboarding_tasks",
    "ingested_event",
    "autocapture_opt_out",
    "autocapture_web_vitals_opt_in",
    "autocapture_web_vitals_allowed_metrics",
    "autocapture_exceptions_opt_in",
    "autocapture_exceptions_errors_to_ignore",
    "person_processing_opt_out",
    "secret_api_token",
    "secret_api_token_backup",
    "session_recording_opt_in",
    "session_recording_sample_rate",
    "session_recording_minimum_duration_milliseconds",
    "session_recording_linked_flag",
    "session_recording_network_payload_capture_config",
    "session_recording_masking_config",
    "session_recording_url_trigger_config",
    "session_recording_url_blocklist_config",
    "session_recording_event_trigger_config",
    "session_recording_trigger_match_type_config",
    "session_replay_config",
    "survey_config",
    "capture_console_log_opt_in",
    "capture_performance_opt_in",
    "capture_dead_clicks",
    "surveys_opt_in",
    "heatmaps_opt_in",
    "flags_persistence_default",
    "feature_flag_confirmation_enabled",
    "feature_flag_confirmation_message",
    "session_recording_version",
    "signup_token",
    "is_demo",
    "access_control",
    "week_start_day",
    "inject_web_apps",
    "test_account_filters",
    "test_account_filters_default_checked",
    "path_cleaning_filters",
    "timezone",
    "data_attributes",
    "person_display_name_properties",
    "live_events_columns",
    "recording_domains",
    "human_friendly_comparison_periods",
    "cookieless_server_hash_mode",
    "primary_dashboard_id",
    "default_data_theme",
    "extra_settings",
    "modifiers",
    "correlation_config",
    "session_recording_retention_period_days",
    "plugins_opt_in",
    "opt_out_capture",
    "event_names",
    "event_names_with_usage",
    "event_properties",
    "event_properties_with_usage",
    "event_properties_numerical",
    "external_data_workspace_id",
    "external_data_workspace_last_synced_at",
    "api_query_rate_limit",
    "revenue_tracking_config",
    "drop_events_older_than",
    "base_currency",
]

_FEATURE_FLAG_COLS = [
    "id",
    "team_id",
    "key",
    "name",
    "filters",
    "deleted",
    "active",
    "archived",
    "version",
    "ensure_experience_continuity",
    "usage_dashboard_id",
    "has_enriched_analytics",
    "is_remote_configuration",
    "has_encrypted_payloads",
    "evaluation_runtime",
    "bucketing_identifier",
    "created_by_id",
    "created_at",
    "updated_at",
]

_SELECT_COLUMNS: dict[str, list[str]] = {
    "posthog_organization": _ORG_COLS,
    "posthog_team": _TEAM_COLS,
    "posthog_featureflag": _FEATURE_FLAG_COLS,
}

# JSON columns selected as ::text for org / team so psycopg2 doesn't parse 30+ fields per row only
# for the transform to json.dumps them back. Flags are the exception: projections need the parsed dict.
_JSONB_TEXT_CAST: dict[str, set[str]] = {
    "posthog_organization": {"available_product_features", "usage", "customer_trust_scores", "personalization"},
    "posthog_team": {
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
    },
    "posthog_featureflag": set(),
}

# psycopg2 already parses jsonb ::text as raw strings; these are the columns that must NOT be re-dumped.
_BOOL_FIELDS: dict[str, list[str]] = {
    "posthog_organization": [
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
    ],
    "posthog_team": [
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
    ],
    "posthog_featureflag": [
        "deleted",
        "active",
        "archived",
        "ensure_experience_continuity",
        "has_enriched_analytics",
        "is_remote_configuration",
        "has_encrypted_payloads",
    ],
}

_UUID_FIELDS: dict[str, list[str]] = {
    "posthog_organization": ["id", "logo_media_id"],
    "posthog_team": ["uuid", "organization_id"],
    "posthog_featureflag": [],
}

_ARRAY_FIELDS: dict[str, list[str]] = {
    "posthog_organization": ["domain_whitelist"],
    "posthog_team": ["app_urls", "person_display_name_properties", "live_events_columns", "recording_domains"],
    "posthog_featureflag": [],
}


def _select_clause(table_name: str) -> str:
    jsonb_cols = _JSONB_TEXT_CAST[table_name]
    return ", ".join(f"{col}::text AS {col}" if col in jsonb_cols else col for col in _SELECT_COLUMNS[table_name])


def _normalize_filters(filters: Any) -> dict[str, Any]:
    """``filters`` arrives as a dict (mocked rows, psycopg2-parsed jsonb); normalize to a dict."""
    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except (TypeError, ValueError):
            return {}
    return filters if isinstance(filters, dict) else {}


def transform_organization_row(row: dict) -> dict:
    for field in _UUID_FIELDS["posthog_organization"]:
        if row.get(field) is not None:
            row[field] = str(row[field])
    for field in _BOOL_FIELDS["posthog_organization"]:
        if row.get(field) is not None:
            row[field] = 1 if row[field] else 0
    for field in _ARRAY_FIELDS["posthog_organization"]:
        if row.get(field) is None:
            row[field] = []
        elif isinstance(row[field], list):
            row[field] = [v for v in row[field] if v is not None]
    return row


def transform_team_row(row: dict) -> dict:
    for field in _UUID_FIELDS["posthog_team"]:
        if row.get(field) is not None:
            row[field] = str(row[field])
    for field in _BOOL_FIELDS["posthog_team"]:
        if row.get(field) is not None:
            row[field] = 1 if row[field] else 0
    if row.get("drop_events_older_than") is not None:
        row["drop_events_older_than"] = int(row["drop_events_older_than"].total_seconds())
    for field in _ARRAY_FIELDS["posthog_team"]:
        if row.get(field) is None:
            row[field] = []
        elif isinstance(row[field], list):
            row[field] = [v for v in row[field] if v is not None]
    return row


def transform_feature_flag_row(row: dict) -> dict:
    filters_dict = _normalize_filters(row.get("filters"))
    row["filters"] = json.dumps(filters_dict)
    for field in _BOOL_FIELDS["posthog_featureflag"]:
        if row.get(field) is not None:
            row[field] = 1 if row[field] else 0
    # Watermark column must never be NULL (it's in ORDER BY and the high-watermark read); a brand-new
    # flag hasn't been edited yet, so fall back to created_at. Makes updated_at non-null in the mirror.
    if row.get("updated_at") is None:
        row["updated_at"] = row.get("created_at")
    cfg = TABLE_CONFIGS["posthog_featureflag"]
    for projection_name, projection_fn in cfg.projections.items():
        row[projection_name] = projection_fn(filters_dict)
    # Deliberately excluded: last_called_at has its own bulk-update writer that bypasses auto_now,
    # so a mirrored column would be permanently stale. See .notes/feature-flag-mirror-design.md.
    row.pop("last_called_at", None)
    return row


_TRANSFORMS: dict[str, Callable[[dict], dict]] = {
    "posthog_organization": transform_organization_row,
    "posthog_team": transform_team_row,
    "posthog_featureflag": transform_feature_flag_row,
}


def transform_row(table_name: str, row: dict) -> dict:
    return _TRANSFORMS[table_name](row)


def fetch_rows_in_batches(conn, table_name: str, last_sync: Optional[datetime], batch_size: int = 10000):
    """Yield batches from Postgres, incrementally filtered on the table's watermark column."""
    cfg = TABLE_CONFIGS[table_name]
    if cfg.postgres_filter is not None:
        where_clause, params = cfg.postgres_filter(last_sync)
    else:
        where_clause, params = (f"WHERE {cfg.watermark_column} > %s", [last_sync]) if last_sync else ("", [])

    query = f"SELECT {_select_clause(table_name)} FROM {table_name} {where_clause} ORDER BY {cfg.watermark_column} ASC"
    cursor = conn.cursor(name=f"{table_name}_cursor_{uuid.uuid4().hex[:8]}")
    try:
        cursor.execute(query, params)
        cursor.itersize = batch_size
        while True:
            batch = cursor.fetchmany(batch_size)
            if not batch:
                break
            yield batch
    finally:
        cursor.close()


def insert_rows_to_clickhouse(table_name: str, rows: list[dict], batch_size: int = 10000) -> int:
    if not rows:
        return 0
    cfg = TABLE_CONFIGS[table_name]
    transformed = [transform_row(table_name, dict(r)) for r in rows]

    columns = _SELECT_COLUMNS[table_name] + list(cfg.projections.keys())
    insert_sql = f"INSERT INTO models.{table_name} ({', '.join(columns)}) VALUES"

    total_inserted = 0
    for i in range(0, len(transformed), batch_size):
        batch = transformed[i : i + batch_size]
        data = [tuple(row.get(col) for col in columns) for row in batch]
        sync_execute(insert_sql, data, with_column_types=False)
        total_inserted += len(batch)
    return total_inserted


def _sync_table(
    context: OpExecutionContext, config: PostgresToClickHouseETLConfig, table_name: str
) -> IncrementalState:
    with tags_context(product=Product.WAREHOUSE, feature=Feature.DATA_MODELING):
        cfg = TABLE_CONFIGS[table_name]
        state = IncrementalState()
        context.log.info(f"Starting {table_name} sync (full_refresh={config.full_refresh})")

        create_clickhouse_tables(context)

        last_sync: Optional[datetime] = None
        if not config.full_refresh:
            result = sync_execute(f"SELECT max({cfg.watermark_column}) FROM models.{table_name}")
            if result and result[0][0]:
                last_sync = result[0][0] - timedelta(seconds=config.backward_lookback_seconds)
                context.log.info(f"Last sync for {table_name}: {last_sync}")
        else:
            context.log.info(f"Full refresh: truncating models.{table_name}")
            try:
                sync_execute(f"TRUNCATE TABLE models.{table_name}")
            except Exception as e:
                context.log.warning(f"Could not truncate (may not exist): {e}")

        pg_conn = get_postgres_connection()
        try:
            total_rows = 0
            batch_num = 0
            for batch in fetch_rows_in_batches(pg_conn, table_name, last_sync, config.batch_size):
                batch_num += 1
                rows_inserted = insert_rows_to_clickhouse(table_name, batch, batch_size=config.batch_size)
                total_rows += rows_inserted
                batch_max = max(
                    (row[cfg.watermark_column] for row in batch if row.get(cfg.watermark_column) is not None),
                    default=None,
                )
                if batch_max is not None and (
                    state.last_sync_timestamp is None or batch_max > state.last_sync_timestamp
                ):
                    state.last_sync_timestamp = batch_max
                context.log.info(f"Batch {batch_num}: +{rows_inserted} → models.{table_name} (total {total_rows})")
            state.rows_synced = total_rows
            context.log.info(f"Completed {table_name} sync: {total_rows} rows")
        finally:
            pg_conn.close()

        return state


def _sync_metadata(context: OpExecutionContext, state: IncrementalState, config: PostgresToClickHouseETLConfig) -> None:
    context.add_output_metadata(
        {
            "rows_synced": MetadataValue.int(state.rows_synced),
            "last_sync_timestamp": MetadataValue.text(
                str(state.last_sync_timestamp) if state.last_sync_timestamp else "N/A"
            ),
            "full_refresh": MetadataValue.bool(config.full_refresh),
        }
    )


@op(retry_policy=etl_retry_policy)
def sync_organizations(context: OpExecutionContext, config: PostgresToClickHouseETLConfig) -> IncrementalState:
    state = _sync_table(context, config, "posthog_organization")
    _sync_metadata(context, state, config)
    return state


@op(retry_policy=etl_retry_policy)
def sync_teams(context: OpExecutionContext, config: PostgresToClickHouseETLConfig) -> IncrementalState:
    state = _sync_table(context, config, "posthog_team")
    _sync_metadata(context, state, config)
    return state


@op(retry_policy=etl_retry_policy)
def sync_feature_flags(context: OpExecutionContext, config: PostgresToClickHouseETLConfig) -> IncrementalState:
    state = _sync_table(context, config, "posthog_featureflag")
    _sync_metadata(context, state, config)
    return state


@op
def verify_sync(
    context: OpExecutionContext,
    org_state: IncrementalState,
    team_state: IncrementalState,
    feature_flag_state: IncrementalState,
) -> dict[str, Any]:
    with tags_context(product=Product.WAREHOUSE, feature=Feature.DATA_MODELING):
        org_count = sync_execute("SELECT count() FROM models.posthog_organization")[0][0]
        team_count = sync_execute("SELECT count() FROM models.posthog_team")[0][0]
        flag_count = sync_execute("SELECT count() FROM models.posthog_featureflag")[0][0]

        counts = {
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
            "feature_flags": {
                "clickhouse_count": flag_count,
                "rows_synced": feature_flag_state.rows_synced,
                "last_sync": str(feature_flag_state.last_sync_timestamp)
                if feature_flag_state.last_sync_timestamp
                else None,
            },
        }
        context.log.info(f"Verification: {counts}")
        context.add_output_metadata(
            {
                "org_count": MetadataValue.int(org_count),
                "team_count": MetadataValue.int(team_count),
                "feature_flag_count": MetadataValue.int(flag_count),
            }
        )
        return counts


hourly_partition = HourlyPartitionsDefinition(start_date="2024-01-01-00:00", timezone="UTC")


@job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value}, partitions_def=hourly_partition)
def postgres_to_clickhouse_etl_job():
    org_state = sync_organizations()
    team_state = sync_teams()
    flag_state = sync_feature_flags()
    verify_sync(org_state, team_state, flag_state)


postgres_to_clickhouse_hourly_schedule = ScheduleDefinition(
    job=postgres_to_clickhouse_etl_job,
    cron_schedule="0 * * * *",
    name="postgres_to_clickhouse_hourly",
    execution_timezone="UTC",
)


def _sync_asset_partition(context: AssetExecutionContext, table_name: str) -> None:
    with tags_context(product=Product.WAREHOUSE, feature=Feature.DATA_MODELING):
        config = PostgresToClickHouseETLConfig()
        create_clickhouse_tables(context)
        partition_dt = datetime.strptime(context.partition_key, "%Y-%m-%d-%H:%M")
        start_time, end_time = partition_dt, partition_dt + timedelta(hours=1)
        cfg = TABLE_CONFIGS[table_name]
        pg_conn = get_postgres_connection()
        try:
            cursor = pg_conn.cursor()
            cursor.execute(
                f"SELECT {_select_clause(table_name)} FROM {table_name} WHERE {cfg.watermark_column} >= %s AND {cfg.watermark_column} < %s ORDER BY {cfg.watermark_column} ASC",
                (start_time, end_time),
            )
            rows = cursor.fetchall()
            context.log.info(f"Fetched {len(rows)} {table_name} rows for partition {context.partition_key}")
            if rows:
                inserted = insert_rows_to_clickhouse(table_name, rows, batch_size=config.batch_size)
                context.log.info(f"Inserted {inserted} rows into models.{table_name}")
            cursor.close()
        finally:
            pg_conn.close()


@asset(
    retry_policy=etl_retry_policy,
    partitions_def=hourly_partition,
    backfill_policy=BackfillPolicy(max_partitions_per_run=24),
)
def organizations_in_clickhouse(context: AssetExecutionContext) -> None:
    _sync_asset_partition(context, "posthog_organization")


@asset(
    retry_policy=etl_retry_policy,
    partitions_def=hourly_partition,
    backfill_policy=BackfillPolicy(max_partitions_per_run=24),
)
def teams_in_clickhouse(context: AssetExecutionContext) -> None:
    _sync_asset_partition(context, "posthog_team")
