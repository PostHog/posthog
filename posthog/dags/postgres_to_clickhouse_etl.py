"""ETL pipeline for syncing posthog_organization, posthog_team, and posthog_featureflag from Postgres to ClickHouse.

Table-driven: every table's columns, DDL, transform behavior, and watermark expression live on one
TableConfig entry. Adding a table means authoring one config entry plus its DDL function.

How correctness is shared with the storage engine:
- Incremental windows overlap by ``TableConfig.lookback_seconds`` (falling back to the job-level
  ``backward_lookback_seconds``) so a row committed after its timestamp slot passed the prior
  high-watermark is still picked up next run. Re-emitting a row the mirror already holds costs
  writes rather than correctness, so flags, the largest mirror, rewinds one hourly cycle while
  orgs and teams absorb a day of missed runs.
- ReplicatedReplacingMergeTree collapses re-emitted rows at merge time, but only for a table whose
  ORDER BY is identity alone. posthog_featureflag qualifies and keeps the newest row by
  ``updated_at``. posthog_organization and posthog_team still trail ``updated_at`` in their ORDER
  BY, so every version gets its own sort key and none of them collapse; a follow-up migration
  reshapes those two. Readers use FINAL / argMax either way.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import field
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

from products.feature_flags.backend.encrypted_flag_payloads import REDACTED_PAYLOAD_VALUE


@frozen
class TableConfig:
    """Declarative description of one Postgres→ClickHouse mirror.

    - ``key``: columns that identify a row across writes. Must be immutable for the life of the row
      so a soft-delete-rename (feature flags rename ``key`` on tombstone) lands as an update, not a
      new identity. The same key drives the ClickHouse ORDER BY prefix. Unused by the sync runner
      today; the reconcile job (follow-up branch) matches rows on it.
    - ``watermark_column``: the non-null change-timestamp column mirrored in ClickHouse and used
      to advance the incremental high-watermark. The transform is responsible for never emitting
      a NULL here (feature flags fall back to ``created_at``).
    - ``watermark_expr``: SQL expression used in place of ``watermark_column`` when filtering and
      ordering the Postgres read, for tables whose watermark column is nullable at the source.
      Flags use COALESCE(updated_at, created_at), matching the coalesced value the mirror stores.
    - ``order_by``: full ClickHouse ORDER BY tuple, and with it the engine's dedup key. Contains
      ``key`` (optionally behind a leading locality column such as ``organization_id`` for teams)
      so same-row versions land in the same part. Anything that changes between versions of a row
      must stay out of it, or those versions stop collapsing.
    - ``select_columns``: Postgres columns to pull, in mirror order.
    - ``jsonb_text_cast``: columns to select as ``col::text`` rather than parsed jsonb, so psycopg2
      doesn't parse 30+ fields per row only for the transform to re-serialize them.
    - ``bool_fields`` / ``uuid_fields`` / ``array_fields``: per-table type adaptations the generic
      transform applies (booleans to 0/1, UUIDs to strings, array NULL-coalescing and
      None-filtering).
    - ``json_dumps_fields``: columns psycopg2 hands over as a Python list or dict that the mirror
      stores as a JSON String. Postgres ``jsonb`` columns take the ``jsonb_text_cast`` route
      instead; this list is for ``ArrayField`` columns, where ``::text`` would render Postgres
      array literal syntax that JSONExtract* cannot read.
    - ``ddl``: callable producing the ``CREATE TABLE IF NOT EXISTS`` SQL for the ClickHouse mirror.
    - ``post_transform``: table-specific row fixups applied after the generic type adaptations.
    - ``lookback_seconds``: how far below the mirror's high-watermark the hourly sync rewinds each
      run, to catch rows that committed after their timestamp slot passed the prior watermark.
      Default 86400; a table overrides it when the rewrite cost of a wide overlap outweighs the
      outage backlog a missing run would leave.
    """

    key: tuple[str, ...]
    watermark_column: str
    order_by: str
    select_columns: list[str]
    ddl: Callable[[], str]
    jsonb_text_cast: set[str] = field(default_factory=set)
    bool_fields: list[str] = field(default_factory=list)
    uuid_fields: list[str] = field(default_factory=list)
    array_fields: list[str] = field(default_factory=list)
    json_dumps_fields: list[str] = field(default_factory=list)
    watermark_expr: Optional[str] = None
    post_transform: Optional[Callable[[dict], dict]] = None
    lookback_seconds: int = 86400

    def select_clause(self) -> str:
        return ", ".join(f"{col}::text AS {col}" if col in self.jsonb_text_cast else col for col in self.select_columns)

    def build_incremental_query(self, table_name: str, last_sync: Optional[datetime]) -> tuple[str, list[Any]]:
        """SELECT everything past the watermark, for the op-based hourly sync."""
        if last_sync is None:
            return self._sql(table_name, ""), []
        return self._sql(table_name, f"WHERE {self._watermark()} > %s"), [last_sync]

    def build_partition_query(self, table_name: str, start: datetime, end: datetime) -> tuple[str, list[Any]]:
        """SELECT one fixed time window, for the asset path's per-hour backfill partitions."""
        watermark = self._watermark()
        return self._sql(table_name, f"WHERE {watermark} >= %s AND {watermark} < %s"), [start, end]

    def _watermark(self) -> str:
        return self.watermark_expr or self.watermark_column

    def _sql(self, table_name: str, where: str) -> str:
        parts = [f"SELECT {self.select_clause()} FROM {table_name}"]
        if where:
            parts.append(where)
        parts.append(f"ORDER BY {self._watermark()} ASC")
        return " ".join(parts)


@frozen
class IncrementalState:
    last_sync_timestamp: Optional[datetime] = None
    rows_synced: int = 0


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


def _normalize_filters(filters: Any) -> dict[str, Any]:
    """``filters`` arrives as a dict (psycopg2-parsed jsonb) or a string (mocked rows); normalize to a dict."""
    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except (TypeError, ValueError):
            return {}
    return filters if isinstance(filters, dict) else {}


# ----- posthog_organization -----

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

_ORG_BOOL_FIELDS = [
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

# available_product_features is ArrayField(JSONField()), not JSONField. Excluded from the cast
# so psycopg2 parses the list and json.dumps round-trips the elements to valid JSON; `jsonb[]::text`
# renders Postgres array literal syntax (`{"{\"key\": \"val\"}"}`), which JSONExtract* cannot read.
_ORG_JSONB_TEXT_CAST = {
    "usage",
    "customer_trust_scores",
    "personalization",
}

_ORG_JSON_DUMPS_FIELDS = ["available_product_features"]


def _organization_ddl() -> str:
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


# ----- posthog_team -----

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

_TEAM_BOOL_FIELDS = [
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

# session_recording_url_trigger_config, session_recording_url_blocklist_config, and
# session_recording_event_trigger_config are ArrayField(JSONField()) / ArrayField(TextField()), not
# JSONField. Excluded from the cast so psycopg2 parses the list and json.dumps round-trips the
# elements to valid JSON; `::text` on an array renders Postgres array literal syntax, which
# JSONExtract* cannot read.
_TEAM_JSONB_TEXT_CAST = {
    "has_completed_onboarding_for",
    "onboarding_tasks",
    "autocapture_web_vitals_allowed_metrics",
    "autocapture_exceptions_errors_to_ignore",
    "session_recording_linked_flag",
    "session_recording_network_payload_capture_config",
    "session_recording_masking_config",
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
}

_TEAM_ARRAY_FIELDS = ["app_urls", "person_display_name_properties", "live_events_columns", "recording_domains"]

_TEAM_JSON_DUMPS_FIELDS = [
    "session_recording_url_trigger_config",
    "session_recording_url_blocklist_config",
    "session_recording_event_trigger_config",
]


def _team_ddl() -> str:
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
            drop_events_older_than Nullable(Int64),  -- stored as seconds (Django interval → total_seconds())
            base_currency Nullable(String),
            _inserted_at DateTime64(6) DEFAULT now64(6)
        )
        ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog_team', '{shard}-{replica}', _inserted_at)
        ORDER BY (organization_id, id, updated_at)
        SETTINGS index_granularity = 8192
    """


def _finalize_team_row(row: dict) -> dict:
    if row.get("drop_events_older_than") is not None:
        row["drop_events_older_than"] = int(row["drop_events_older_than"].total_seconds())
    return row


# ----- posthog_featureflag -----

# last_called_at is deliberately excluded: it has its own bulk-update writer that bypasses auto_now,
# so a mirrored column would be permanently stale. See .notes/feature-flag-mirror-design.md.
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

_FEATURE_FLAG_BOOL_FIELDS = [
    "deleted",
    "active",
    "archived",
    "ensure_experience_continuity",
    "has_enriched_analytics",
    "is_remote_configuration",
    "has_encrypted_payloads",
]

# ReplacingMergeTree collapses rows sharing the full ORDER BY tuple, so the tuple is identity only:
# adding updated_at would give every edit its own sort key and the mirror would keep every version.
_FEATURE_FLAG_ORDER_BY = "(team_id, id)"

# updated_at is NULL until a flag's first edit, so Postgres-side filtering and ordering fall back
# to created_at. The transform applies the same coalesce before insert, so the mirror's watermark
# read and this expression always agree.
_FEATURE_FLAG_WATERMARK_EXPR = "COALESCE(updated_at, created_at)"


def _feature_flag_ddl() -> str:
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
            _inserted_at DateTime64(6) DEFAULT now64(6)
        )
        ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog_featureflag', '{{shard}}-{{replica}}', updated_at)
        ORDER BY {_FEATURE_FLAG_ORDER_BY}
        SETTINGS index_granularity = 8192
    """


def _finalize_feature_flag_row(row: dict) -> dict:
    # Normalizing guarantees a non-null JSON object for the non-Nullable String column, even when
    # the source value is NULL or unparseable.
    filters_dict = _normalize_filters(row.get("filters"))
    payloads = filters_dict.get("payloads")
    if isinstance(payloads, dict) and payloads:
        # Rotate-through-update commands (e.g. reencrypt_flag_payloads) bypass auto_now, so the
        # incremental mirror never sees a rotation. Substituting ciphertext with the API redaction
        # sentinel keeps the variant-key shape intact without persisting ciphertext in ClickHouse.
        filters_dict = {**filters_dict, "payloads": dict.fromkeys(payloads, REDACTED_PAYLOAD_VALUE)}
    row["filters"] = json.dumps(filters_dict)
    # Watermark column must never be NULL (it's in ORDER BY and the high-watermark read); a brand-new
    # flag hasn't been edited yet, so fall back to created_at. Makes updated_at non-null in the mirror.
    if row.get("updated_at") is None:
        row["updated_at"] = row.get("created_at")
    return row


# ----- TABLE_CONFIGS -----

TABLE_CONFIGS: dict[str, TableConfig] = {
    "posthog_organization": TableConfig(
        key=("id",),
        watermark_column="updated_at",
        order_by="(id, updated_at)",
        select_columns=_ORG_COLS,
        jsonb_text_cast=_ORG_JSONB_TEXT_CAST,
        bool_fields=_ORG_BOOL_FIELDS,
        uuid_fields=["id", "logo_media_id"],
        array_fields=["domain_whitelist"],
        json_dumps_fields=_ORG_JSON_DUMPS_FIELDS,
        ddl=_organization_ddl,
    ),
    "posthog_team": TableConfig(
        key=("id",),
        watermark_column="updated_at",
        order_by="(organization_id, id, updated_at)",
        select_columns=_TEAM_COLS,
        jsonb_text_cast=_TEAM_JSONB_TEXT_CAST,
        bool_fields=_TEAM_BOOL_FIELDS,
        uuid_fields=["uuid", "organization_id"],
        array_fields=_TEAM_ARRAY_FIELDS,
        json_dumps_fields=_TEAM_JSON_DUMPS_FIELDS,
        ddl=_team_ddl,
        post_transform=_finalize_team_row,
    ),
    # Identity is (team_id, id), not (team_id, key): soft-delete renames key with a :deleted:<id>
    # suffix, and id is what survives that rename.
    "posthog_featureflag": TableConfig(
        key=("team_id", "id"),
        watermark_column="updated_at",
        watermark_expr=_FEATURE_FLAG_WATERMARK_EXPR,
        order_by=_FEATURE_FLAG_ORDER_BY,
        select_columns=_FEATURE_FLAG_COLS,
        bool_fields=_FEATURE_FLAG_BOOL_FIELDS,
        # Flags re-emit the largest mirror, so one hourly cycle of overlap is enough; orgs and
        # teams keep the outsized 24h outage window from the default.
        ddl=_feature_flag_ddl,
        post_transform=_finalize_feature_flag_row,
        lookback_seconds=3600,
    ),
}


class PostgresToClickHouseETLConfig(Config):
    full_refresh: bool = False
    batch_size: int = 10000
    # Fallback overlap for tables whose TableConfig leaves lookback_seconds at its default. A
    # table's own lookback_seconds (posthog_featureflag) wins over this when set non-default.
    backward_lookback_seconds: int = 86400


etl_retry_policy = RetryPolicy(
    max_retries=3,
    delay=60,
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.PLUS_MINUS,
)


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
    for table_name, cfg in TABLE_CONFIGS.items():
        if context:
            context.log.info(f"Creating models.{table_name} if it doesn't exist...")
        cluster.map_all_hosts(Query(cfg.ddl())).result()


def transform_row(table_name: str, row: dict) -> dict:
    """Adapt one Postgres row dict for the ClickHouse mirror, in place."""
    cfg = TABLE_CONFIGS[table_name]
    for f in cfg.uuid_fields:
        if row.get(f) is not None:
            row[f] = str(row[f])
    for f in cfg.bool_fields:
        if row.get(f) is not None:
            row[f] = 1 if row[f] else 0
    for f in cfg.array_fields:
        if row.get(f) is None:
            row[f] = []
        elif isinstance(row[f], list):
            row[f] = [v for v in row[f] if v is not None]
    for f in cfg.json_dumps_fields:
        if row.get(f) is not None:
            row[f] = json.dumps(row[f])
    return cfg.post_transform(row) if cfg.post_transform else row


def fetch_rows_in_batches(conn, table_name: str, last_sync: Optional[datetime], batch_size: int = 10000):
    """Yield batches from Postgres, incrementally filtered on the table's watermark expression."""
    cfg = TABLE_CONFIGS[table_name]
    query, params = cfg.build_incremental_query(table_name, last_sync)

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

    insert_sql = f"INSERT INTO models.{table_name} ({', '.join(cfg.select_columns)}) VALUES"

    total_inserted = 0
    for i in range(0, len(transformed), batch_size):
        batch = transformed[i : i + batch_size]
        # row[col], not row.get(col): a missing configured column is a bug (transform drift, config
        # typo), and a KeyError naming the column beats inserting NULL into a required field.
        data = [tuple(row[col] for col in cfg.select_columns) for row in batch]
        sync_execute(insert_sql, data, with_column_types=False)
        total_inserted += len(batch)
    return total_inserted


def _sync_table(
    context: OpExecutionContext, config: PostgresToClickHouseETLConfig, table_name: str
) -> IncrementalState:
    with tags_context(product=Product.WAREHOUSE, feature=Feature.DATA_MODELING):
        cfg = TABLE_CONFIGS[table_name]
        context.log.info(f"Starting {table_name} sync (full_refresh={config.full_refresh})")

        create_clickhouse_tables(context)

        last_sync: Optional[datetime] = None
        if not config.full_refresh:
            # nosemgrep: clickhouse-fstring-param-audit - table_name is a TABLE_CONFIGS key from the job config allowlist; watermark_column is code-controlled
            result = sync_execute(f"SELECT max({cfg.watermark_column}) FROM models.{table_name}")
            if result and result[0][0]:
                lookback = cfg.lookback_seconds if cfg.lookback_seconds != 86400 else config.backward_lookback_seconds
                last_sync = result[0][0] - timedelta(seconds=lookback)
                context.log.info(f"Last sync for {table_name}: {last_sync}")
        else:
            context.log.info(f"Full refresh: truncating models.{table_name}")
            try:
                # nosemgrep: clickhouse-fstring-param-audit - table_name is a TABLE_CONFIGS key from the job config allowlist
                sync_execute(f"TRUNCATE TABLE models.{table_name}")
            except Exception as e:
                context.log.warning(f"Could not truncate (may not exist): {e}")

        pg_conn = get_postgres_connection()
        try:
            total_rows = 0
            batch_num = 0
            watermark: Optional[datetime] = None
            for batch in fetch_rows_in_batches(pg_conn, table_name, last_sync, config.batch_size):
                batch_num += 1
                rows_inserted = insert_rows_to_clickhouse(table_name, batch, batch_size=config.batch_size)
                total_rows += rows_inserted
                batch_max = max(
                    (row[cfg.watermark_column] for row in batch if row.get(cfg.watermark_column) is not None),
                    default=None,
                )
                if batch_max is not None and (watermark is None or batch_max > watermark):
                    watermark = batch_max
                context.log.info(f"Batch {batch_num}: +{rows_inserted} → models.{table_name} (total {total_rows})")
            context.log.info(f"Completed {table_name} sync: {total_rows} rows")
        finally:
            pg_conn.close()

        return IncrementalState(last_sync_timestamp=watermark, rows_synced=total_rows)


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
        # partition_time_window raises the moment the run covers a multi-partition range; the
        # backfill policy allows up to 24 partitions per run, so taking it off the context
        # (rather than context.partition_key) is what makes range backfills actually work.
        window = context.partition_time_window
        start_time, end_time = window.start, window.end
        cfg = TABLE_CONFIGS[table_name]
        query, params = cfg.build_partition_query(table_name, start_time, end_time)
        pg_conn = get_postgres_connection()
        try:
            cursor = pg_conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            context.log.info(f"Fetched {len(rows)} {table_name} rows for partition window {start_time}..{end_time}")
            if rows:
                inserted = insert_rows_to_clickhouse(table_name, rows, batch_size=config.batch_size)
                context.log.info(f"Inserted {inserted} rows into models.{table_name}")
            cursor.close()
        finally:
            pg_conn.close()


def _hourly_backfill_asset(name: str, table_name: str):
    """Build a partitioned asset that mirrors one UTC hour of ``table_name`` per materialization.

    Manual escape hatch alongside the scheduled hourly job: materialize a partition range from the
    Dagster UI to re-sync a known time window (for example after an incident or a missed run).
    """

    @asset(
        name=name,
        retry_policy=etl_retry_policy,
        partitions_def=hourly_partition,
        backfill_policy=BackfillPolicy(max_partitions_per_run=24),
    )
    def _backfill(context: AssetExecutionContext) -> None:
        _sync_asset_partition(context, table_name)

    return _backfill


organizations_in_clickhouse = _hourly_backfill_asset("organizations_in_clickhouse", "posthog_organization")
teams_in_clickhouse = _hourly_backfill_asset("teams_in_clickhouse", "posthog_team")
feature_flags_in_clickhouse = _hourly_backfill_asset("feature_flags_in_clickhouse", "posthog_featureflag")
