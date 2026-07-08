from __future__ import annotations

import uuid
import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

import structlog
import temporalio
from dateutil import parser
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_field
from openai import APIConnectionError
from psycopg import OperationalError
from rest_framework import filters, serializers, status, viewsets
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from sshtunnel import BaseSSHTunnelForwarderError

from posthog.schema import (
    SourceFieldFileUploadConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)

from posthog.hogql.database.database import Database
from posthog.hogql.direct_sql.capability import direct_capable_source_types

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models.user import User
from posthog.rate_limit import (
    CustomSourceAIBuilderBurstThrottle,
    CustomSourceAIBuilderDailyThrottle,
    CustomSourceAIBuilderSustainedThrottle,
)
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from products.cdp.backend.facade.api import HogFunctionSerializer
from products.cdp.backend.facade.models import HogFunction
from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
from products.data_warehouse.backend.facade.api import (
    apply_on_refresh as apply_sql_warehouse_refresh_migration,
    apply_on_schema_clear as apply_sql_warehouse_schema_clear_migration,
    bulk_create_external_data_job_schedules,
    bulk_delete_external_data_schedules,
    cancel_external_data_workflow,
    create_and_register_webhook,
    delete_cdc_extraction_schedule,
    delete_discover_schemas_schedule,
    delete_external_data_schedule,
    delete_webhook_and_hog_function,
    detect_schema_clear_transition as detect_sql_schema_clear_transition,
    ensure_cdc_slot_cleanup_schedule,
    get_mysql_source_location,
    get_or_create_webhook_hog_function,
    get_postgres_source_location,
    get_webhook_url,
    is_any_external_data_schema_paused,
    is_cdc_enabled_for_team,
    is_custom_source_ai_builder_enabled_for_team,
    is_multi_schema_capable_sql_source,
    is_xmin_enabled_for_team,
    reconcile_mysql_schemas,
    reconcile_postgres_schemas,
    reconcile_refresh_name_substitutions as reconcile_postgres_refresh_name_substitutions,
    reconcile_snowflake_schemas,
    source_namespace_is_blank,
    sync_cdc_extraction_schedule,
    sync_discover_schemas_schedule,
    sync_external_data_job_workflow,
    trigger_external_data_source_workflow,
    upsert_direct_mysql_table,
    upsert_direct_postgres_table,
    upsert_direct_snowflake_table,
)
from products.data_warehouse.backend.facade.models import ExternalDataSourceRevenueAnalyticsConfig
from products.data_warehouse.backend.presentation.views.external_data_schema import (
    ExternalDataSchemaSerializer,
    RowFiltersField,
    SimpleExternalDataSchemaSerializer,
    source_supports_column_selection,
    unsupported_row_filter_reason,
)
from products.data_warehouse.backend.presentation.views.public_source_configs import build_source_configs
from products.revenue_analytics.backend.facade.api import ensure_person_join, remove_person_join
from products.warehouse_sources.backend.facade.api import (
    mysql_columns_to_dwh_columns,
    postgres_columns_to_dwh_columns,
    snowflake_columns_to_dwh_columns,
    validate_source_prefix,
)
from products.warehouse_sources.backend.facade.models import (
    CustomOAuth2Integration,
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
    PendingSourceCredential,
    sync_old_schemas_with_new_schemas,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.facade.source_management import (
    DEFAULT_LAG_CRITICAL_THRESHOLD_MB,
    DEFAULT_LAG_WARNING_THRESHOLD_MB,
    MAX_CUSTOM_SOURCES_PER_TEAM,
    PREVIEW_DEFAULT_ROWS,
    PREVIEW_MAX_ROWS,
    AnySource,
    CDCSourceAdapter,
    ClickHouseSource,
    Config,
    CustomSource,
    CustomSourceConfig,
    DocsFetchError,
    ExternalWebhookInfo,
    FieldType,
    MySQLSource,
    PostgresSource,
    RowFilterValidationError,
    SourceRegistry,
    SourceSchema,
    SQLSource,
    SSLRequiredError,
    WebhookSource,
    build_default_schemas,
    cdc_pg_connection,
    draft_manifest_sync,
    fetch_docs_text,
    filter_dwh_columns_by_enabled_columns,
    get_cdc_adapter,
    get_primary_key_columns,
    manifest_request_hosts,
    source_requires_ssl,
    source_type_supports_cdc,
    sql_schema_metadata,
    validate_and_coerce_row_filters,
)
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind, ExternalDataSourceType

logger = structlog.get_logger(__name__)

REFRESH_SCHEMAS_FALLBACK_ERROR_MESSAGE = "Could not fetch schemas from source."

REFRESH_SCHEMAS_EXPECTED_ERROR_MESSAGES = {
    "timeout": "Connection timed out while fetching schemas from the source.",
    "timed out": "Connection timed out while fetching schemas from the source.",
    "connection refused": "Could not connect to the source. Check the host, port, and network access.",
    "could not connect": "Could not connect to the source. Check the host, port, and network access.",
    "could not translate host name": "Could not resolve the source host.",
    "name or service not known": "Could not resolve the source host.",
    "network is unreachable": "Could not reach the source network.",
    "no route to host": "Could not reach the source host.",
    "access denied": "Could not authenticate with the source. Check the connection credentials.",
    "authentication failed": "Could not authenticate with the source. Check the connection credentials.",
    "password authentication failed": "Could not authenticate with the source. Check the connection credentials.",
    "unauthorized": "Could not authenticate with the source. Check the connection credentials.",
    "forbidden": "The source credentials do not have permission to fetch schemas.",
    "ssl/tls connection is required": "SSL/TLS is required to connect to the source.",
    "could not establish session to ssh gateway": "Could not establish an SSH tunnel to the source.",
}


def _exception_text(error: Exception) -> str:
    message = " ".join(str(arg) for arg in error.args if arg is not None) or str(error)
    return f"{type(error).__name__}: {message}"


def _classify_refresh_schemas_error(source: AnySource | None, error: Exception) -> tuple[str, bool]:
    error_text = _exception_text(error)
    normalized_error_text = error_text.lower()
    matched_source_error = False

    if source is not None:
        for pattern, friendly_message in source.get_non_retryable_errors().items():
            if pattern and pattern.lower() in normalized_error_text:
                if friendly_message:
                    return friendly_message, True
                matched_source_error = True

    for pattern, friendly_message in REFRESH_SCHEMAS_EXPECTED_ERROR_MESSAGES.items():
        if pattern in normalized_error_text:
            return friendly_message, True

    if matched_source_error:
        return REFRESH_SCHEMAS_FALLBACK_ERROR_MESSAGE, True

    return REFRESH_SCHEMAS_FALLBACK_ERROR_MESSAGE, False


def get_sensitive_field_names(fields: list[FieldType]) -> set[str]:
    """Extract field names that contain sensitive data from a source config's fields."""
    sensitive: set[str] = set()
    for field in fields:
        if isinstance(field, SourceFieldInputConfig) and (
            field.type == SourceFieldInputConfigType.PASSWORD or field.secret
        ):
            sensitive.add(field.name)
        elif isinstance(field, SourceFieldFileUploadConfig):
            sensitive.add(field.name)
        elif isinstance(field, SourceFieldSwitchGroupConfig):
            sensitive.update(get_sensitive_field_names(field.fields))
        elif isinstance(field, SourceFieldSelectConfig):
            for option in field.options:
                if option.fields:
                    sensitive.update(get_sensitive_field_names(option.fields))
    return sensitive


def _add_name_variants(target: set[str], name: str) -> None:
    """Add a field name and its underscore variant to a set.

    Source field names may use hyphens (e.g. "temporary-dataset") while
    dataclasses.asdict() persists the snake_case field name ("temporary_dataset").
    We need to recognise both forms when classifying persisted job_inputs.
    """
    target.add(name)
    normalised = name.replace("-", "_")
    if normalised != name:
        target.add(normalised)


def get_nonsensitive_and_sensitive_field_names(fields: list[FieldType]) -> tuple[set[str], set[str]]:
    """Classify source config field names as nonsensitive or sensitive.

    Returns (nonsensitive, sensitive) sets of field names, flattened across all nesting levels.
    """
    nonsensitive: set[str] = set()
    sensitive: set[str] = set()

    for field in fields:
        if isinstance(field, SourceFieldInputConfig):
            if field.type == SourceFieldInputConfigType.PASSWORD or field.secret:
                _add_name_variants(sensitive, field.name)
            else:
                _add_name_variants(nonsensitive, field.name)
        elif isinstance(field, SourceFieldFileUploadConfig):
            _add_name_variants(sensitive, field.name)
        elif isinstance(field, SourceFieldSelectConfig):
            _add_name_variants(nonsensitive, field.name)
            for option in field.options:
                if option.fields:
                    ns, s = get_nonsensitive_and_sensitive_field_names(option.fields)
                    nonsensitive.update(ns)
                    sensitive.update(s)
        elif isinstance(field, SourceFieldSwitchGroupConfig):
            _add_name_variants(nonsensitive, field.name)
            ns, s = get_nonsensitive_and_sensitive_field_names(field.fields)
            nonsensitive.update(ns)
            sensitive.update(s)
        elif isinstance(field, SourceFieldOauthConfig):
            _add_name_variants(nonsensitive, field.name)
        elif isinstance(field, SourceFieldSSHTunnelConfig):
            _add_name_variants(nonsensitive, field.name)
            # SSH tunnel has a known nested structure not declared in the field tree.
            # "auth"/"auth_type" are container keys for SSHTunnelAuthConfig.
            nonsensitive.update({"host", "port", "username", "auth", "auth_type", "require_tls"})
            sensitive.update({"password", "passphrase", "private_key"})

    return nonsensitive, sensitive


# Config metadata keys that are always safe to include in nested dicts
_CONFIG_META_KEYS = {"selection", "enabled"}

# CDC config lives in job_inputs but isn't part of any source's user-facing form field
# tree, so it would otherwise be stripped from API reads as "unknown". None of these are
# secrets — they're operational config the Configuration page needs to render CDC state.
_CDC_EXPOSED_JOB_INPUT_KEYS = {
    "cdc_enabled",
    "cdc_management_mode",
    "cdc_slot_name",
    "cdc_publication_name",
    "cdc_auto_drop_slot",
    "cdc_lag_warning_threshold_mb",
    "cdc_lag_critical_threshold_mb",
    "cdc_consistent_point",
}


def strip_sensitive_from_dict(data: dict, nonsensitive: set[str], sensitive: set[str]) -> dict:
    """Return a copy of data with sensitive and unknown keys removed.

    Keys in the nonsensitive set or config metadata keys are kept.
    Keys in the sensitive set or not in any known set are stripped.
    Nested dicts are processed recursively.
    """
    result: dict = {}
    for key, value in data.items():
        if key in sensitive:
            continue
        if key not in nonsensitive and key not in _CONFIG_META_KEYS:
            continue
        if isinstance(value, dict):
            result[key] = strip_sensitive_from_dict(value, nonsensitive, sensitive)
        else:
            result[key] = value
    return result


# Fields whose change could redirect the database connection to a different server
# (and therefore exfiltrate credentials via a poisoned SSH tunnel — VERIA-311).
_SSH_TUNNEL_CONNECTION_FIELDS = ("enabled", "host", "port")

# Top-level job_input fields that name the connection target. Changing any of them
# repoints the source at a different server, so preserved credentials must not be
# reused without re-entry (e.g. ServiceNow's `instance_url` could otherwise be swapped
# to an attacker host that then receives the stored API key / password — VERIA-311).
_CONNECTION_TARGET_FIELDS = ("host", "instance_url")


def ssh_tunnel_connection_changed(existing: Any, incoming: Any) -> bool:
    """True if the SSH tunnel's connection target (enabled/host/port) changed.

    Scalars are coerced to strings to ignore type drift between stored values
    (often strings) and JSON-parsed input (bools/ints). Only `None` collapses to ""
    — `or ""` would also swallow falsy-but-meaningful values like `False` and 0,
    making stored "False" falsely diverge from JSON `false`.
    """
    existing = existing if isinstance(existing, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}

    def _coerce(value: Any) -> str:
        return "" if value is None else str(value)

    return any(_coerce(existing.get(key)) != _coerce(incoming.get(key)) for key in _SSH_TUNNEL_CONNECTION_FIELDS)


# Nested SourceFieldSelectConfig containers (Stripe `auth_method`, Snowflake `auth_type`,
# ServiceNow `auth_method`) keep their secrets one level down, not at the top level.
_NESTED_AUTH_CONTAINERS = ("auth_method", "auth_type")

# Secrets the edit form can never re-supply (parsed into the individual fields on create, then
# stripped from API reads and hidden in the edit form), so gating credential re-entry on them would
# permanently block host changes. Excluded from the gate but still preserved by the merge: MongoDB
# connects via `connection_string`, while SQL sources use the individual fields and gate `password`.
_CREATION_ONLY_SECRET_FIELDS = frozenset({"connection_string"})


def has_preserved_credentials(existing: dict[str, Any], incoming: dict[str, Any], sensitive_fields: set[str]) -> bool:
    """True if any stored secret would be reused because the update didn't re-supply it.

    Checks both top-level secret fields and the nested auth containers where sources like
    ServiceNow, Stripe and Snowflake keep their credentials. Used to force credential
    re-entry when the connection target changes, so a redirected host can't receive a
    preserved secret. A secret only counts as preserved when it would survive the merge:
    an absent container carries the whole existing block over, a same-selection container
    preserves any field the update omits, and a selection switch replaces the block wholesale.
    """
    if any(existing.get(key) and not incoming.get(key) for key in sensitive_fields):
        return True

    for container_key in _NESTED_AUTH_CONTAINERS:
        existing_container = existing.get(container_key)
        if not isinstance(existing_container, dict):
            continue
        incoming_container = incoming.get(container_key)
        if not isinstance(incoming_container, dict):
            # Container not re-supplied — the existing secrets carry over wholesale.
            if any(existing_container.get(key) for key in sensitive_fields):
                return True
            continue
        if existing_container.get("selection") != incoming_container.get("selection"):
            continue
        if any(existing_container.get(key) and not incoming_container.get(key) for key in sensitive_fields):
            return True

    return False


def get_direct_connection_metadata(
    *,
    source_impl: Any,
    source_config: Config,
    team_id: int,
    source_model: ExternalDataSource | None = None,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata_fetcher = getattr(source_impl, "get_connection_metadata", None)
    if not callable(metadata_fetcher):
        return fallback or {}

    require_ssl = source_model is not None and source_requires_ssl(source_model, source_config)

    try:
        metadata = metadata_fetcher(source_config, team_id, require_ssl=require_ssl)
    except Exception as error:
        # Connection metadata is best-effort — we fall back below regardless. An expected
        # user/upstream connection failure (unreachable or misconfigured host, refused connection,
        # bad credentials) is the customer's to fix and is already surfaced by credential
        # validation, so don't capture it as error-tracking noise. Mirrors `refresh_schemas`.
        _, is_expected_source_error = _classify_refresh_schemas_error(source_impl, error)
        if not is_expected_source_error:
            capture_exception(error)
        return fallback or {}

    return metadata if isinstance(metadata, dict) else (fallback or {})


def get_postgres_source_table_location(
    *,
    schema_name: str,
    source_schema: SourceSchema | None,
    default_schema: str | None,
) -> tuple[str | None, str, str]:
    return get_postgres_source_location(
        schema_name=schema_name,
        schema_metadata={
            "source_catalog": source_schema.source_catalog if source_schema else None,
            "source_schema": source_schema.source_schema if source_schema else None,
            "source_table_name": source_schema.source_table_name if source_schema else None,
        },
        default_schema=default_schema,
    )


def get_mysql_source_table_location(
    *,
    schema_name: str,
    source_schema: SourceSchema | None,
    default_schema: str | None,
) -> tuple[str, str]:
    return get_mysql_source_location(
        schema_name=schema_name,
        schema_metadata={
            "source_schema": source_schema.source_schema if source_schema else None,
            "source_table_name": source_schema.source_table_name if source_schema else None,
        },
        default_schema=default_schema,
    )


def get_snowflake_source_table_location(
    *,
    schema_name: str,
    source_schema: SourceSchema | None,
    default_schema: str | None,
    default_catalog: str | None = None,
) -> tuple[str | None, str, str]:
    catalog = source_schema.source_catalog if source_schema and source_schema.source_catalog else default_catalog
    if source_schema and source_schema.source_schema and source_schema.source_table_name:
        return catalog, source_schema.source_schema, source_schema.source_table_name

    normalized_default_schema = (
        default_schema.strip() if isinstance(default_schema, str) and default_schema.strip() else None
    )
    if normalized_default_schema is None and "." in schema_name:
        inferred_schema, inferred_table_name = schema_name.split(".", 1)
        return catalog, inferred_schema, inferred_table_name

    return catalog, normalized_default_schema or "", schema_name


CUSTOM_SOURCE_LIMIT_MESSAGE = f"You can create at most {MAX_CUSTOM_SOURCES_PER_TEAM} custom sources per project."
DIRECT_QUERY_UNSUPPORTED_SOURCE_MESSAGE = (
    "Direct query mode is currently supported only for Postgres, MySQL, and Snowflake sources."
)
# Engines surfaced on a direct connection's `connection_metadata.engine` (duckdb backs direct Postgres).
DIRECT_CONNECTION_ENGINE_CHOICES = ["duckdb", "postgres", "mysql", "snowflake"]


def count_active_custom_sources(team_id: int) -> int:
    return (
        ExternalDataSource.objects.filter(team_id=team_id, source_type=ExternalDataSourceType.CUSTOM)
        .exclude(deleted=True)
        .count()
    )


class ExternalDataSourceRevenueAnalyticsConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalDataSourceRevenueAnalyticsConfig
        fields = ["enabled", "include_invoiceless_charges"]


class ExternalDataSourceConnectionMetadataSerializer(serializers.Serializer):
    database = serializers.CharField(
        read_only=True,
        required=False,
        allow_null=True,
        help_text="Database name discovered for a direct connection.",
    )
    version = serializers.CharField(
        read_only=True,
        required=False,
        allow_null=True,
        help_text="Database version string reported by the direct connection.",
    )
    engine = serializers.ChoiceField(
        read_only=True,
        required=False,
        allow_null=True,
        choices=DIRECT_CONNECTION_ENGINE_CHOICES,
        help_text="Backend engine detected for the direct connection.",
    )
    function_source = serializers.CharField(
        read_only=True,
        required=False,
        allow_null=True,
        help_text="System catalog or function source used to discover supported functions.",
    )
    available_functions = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        required=False,
        help_text="Functions discovered as available on the direct connection.",
    )


class ExternalDataSourceConnectionOptionSerializer(serializers.ModelSerializer):
    engine = serializers.ChoiceField(
        source="connection_metadata.engine",
        read_only=True,
        allow_null=True,
        choices=DIRECT_CONNECTION_ENGINE_CHOICES,
        help_text="Backend engine detected for the direct connection.",
    )

    class Meta:
        model = ExternalDataSource
        fields = ["id", "prefix", "engine"]
        read_only_fields = ["id", "prefix", "engine"]


class ExternalDataSourceBulkUpdateSchemaSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Schema identifier to update.")
    should_sync = serializers.BooleanField(required=False, help_text="Whether the schema should be queryable/synced.")
    sync_type = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=ExternalDataSchema.SyncType.choices,
        help_text="Requested sync mode for the schema (incremental, full_refresh, append, cdc, or xmin).",
    )
    incremental_field = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Incremental cursor field for incremental or append syncs.",
    )
    incremental_field_type = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Type of the incremental cursor field.",
    )
    sync_frequency = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Human-readable sync frequency value.",
    )
    sync_time_of_day = serializers.TimeField(
        required=False,
        allow_null=True,
        help_text="UTC anchor time for scheduled syncs.",
    )
    cdc_table_mode = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=["consolidated", "cdc_only", "both"],
        help_text="How CDC-backed tables should be exposed.",
    )
    enabled_columns = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        allow_empty=True,
        help_text="Columns to sync. Null means sync all columns.",
    )
    row_filters = RowFiltersField(
        required=False,
        allow_null=True,
        help_text="Row-filter predicates ANDed onto the source query. Null/empty means sync all rows.",
    )


class ExternalDataSourceBulkUpdateSchemasSerializer(serializers.Serializer):
    schemas = ExternalDataSourceBulkUpdateSchemaSerializer(
        many=True,
        allow_empty=False,
        help_text="Schema updates to apply in a single batch.",
    )


def _validation_error_message(error: ValidationError) -> str:
    # DRF normalizes ValidationError.detail to a list or dict (never a bare string).
    detail = error.detail
    if isinstance(detail, dict):
        return " ".join(f"{field}: {value}" for field, value in detail.items())
    return " ".join(str(item) for item in detail)


class BulkSchemaSaveError(APIException):
    default_code = "bulk_schema_save_failed"

    def __init__(self, failures: dict[str, tuple[str, str]], *, only_validation_errors: bool) -> None:
        # Pure input problems are the caller's to fix (400). A database/infra error is ours and is
        # retryable (503); treat a mix as a server problem so it surfaces as retryable.
        self.status_code = (
            status.HTTP_400_BAD_REQUEST if only_validation_errors else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        reasons = "; ".join(f"{name} ({reason})" for name, reason in failures.values())
        super().__init__(
            detail=(
                f"These schemas in the batch could not be saved: {reasons}. "
                "Any other schemas in the batch were saved successfully — retry the ones listed here."
            )
        )


class ExternalDataJobSerializers(serializers.ModelSerializer):
    schema = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    cdc_write_mode = serializers.SerializerMethodField(
        read_only=True,
        help_text=(
            "For CDC syncs with `cdc_table_mode='both'`, distinguishes the two ExternalDataJob "
            "rows produced per sync: `incremental_merge` (consolidated table) vs `scd2_append` "
            "(cdc-only history table). `null` for non-CDC syncs. Read from `schema_snapshot`."
        ),
    )

    class Meta:
        model = ExternalDataJob
        fields = [
            "id",
            "created_at",
            "created_by",
            "finished_at",
            "status",
            "schema",
            "rows_synced",
            "latest_error",
            "workflow_run_id",
            "cdc_write_mode",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "finished_at",
            "status",
            "schema",
            "rows_synced",
            "latest_error",
            "workflow_run_id",
            "cdc_write_mode",
        ]

    def get_cdc_write_mode(self, instance: ExternalDataJob) -> str | None:
        return (instance.schema_snapshot or {}).get("cdc_write_mode")

    def get_status(self, instance: ExternalDataJob):
        if instance.status == ExternalDataJob.Status.BILLING_LIMIT_REACHED:
            return "Billing limits"

        if instance.status == ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW:
            return "Billing limit too low"

        return instance.status

    def get_schema(self, instance: ExternalDataJob):
        return SimpleExternalDataSchemaSerializer(
            instance.schema, many=False, read_only=True, context=self.context
        ).data


class ExternalDataSourceSerializers(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    account_id = serializers.CharField(write_only=True)
    client_secret = serializers.CharField(write_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)
    created_by = serializers.SerializerMethodField(read_only=True)
    latest_error = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    schemas = serializers.SerializerMethodField(read_only=True)
    engine = serializers.ChoiceField(
        source="connection_metadata.engine",
        read_only=True,
        allow_null=True,
        required=False,
        choices=DIRECT_CONNECTION_ENGINE_CHOICES,
        help_text="Backend engine detected for the direct connection.",
    )
    revenue_analytics_config = ExternalDataSourceRevenueAnalyticsConfigSerializer(
        source="revenue_analytics_config_safe", read_only=True
    )
    access_method = serializers.ChoiceField(choices=ExternalDataSource.AccessMethod.choices, read_only=True)
    supports_webhooks = serializers.SerializerMethodField(read_only=True)
    supports_column_selection = serializers.SerializerMethodField(
        read_only=True,
        help_text="Whether this source supports per-column sync selection via `enabled_columns`.",
    )
    # Optional on both create and update. On create, missing values default to `api`
    # in the viewset to preserve backward compatibility with direct API callers that
    # predate this field; the in-app UI and MCP tool always send it explicitly.
    # `update` strips it to make the field write-once.
    # `allow_null=True` because historical rows (created before migration 0049) have
    # `created_via=NULL`, and the settings page spreads the GET payload back into PATCH.
    created_via = serializers.ChoiceField(
        choices=ExternalDataSource.CreatedVia.choices,
        required=False,
        allow_null=True,
        help_text=(
            "How this source was created. Defaults to `api` on create when omitted. "
            "`web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls. "
            "Ignored on update."
        ),
    )
    direct_query_enabled = serializers.BooleanField(
        required=False,
        help_text=(
            "Whether this synced source is also live-queryable via direct connection. "
            "Defaults to true for new sources; ignored for pure direct-query sources."
        ),
    )

    class Meta:
        model = ExternalDataSource
        fields = [
            "id",
            "created_at",
            "created_by",
            "created_via",
            "status",
            "client_secret",
            "account_id",
            "source_type",
            "latest_error",
            "prefix",
            "description",
            "access_method",
            "direct_query_enabled",
            "engine",
            "last_run_at",
            "schemas",
            "job_inputs",
            "revenue_analytics_config",
            "user_access_level",
            "supports_webhooks",
            "supports_column_selection",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "status",
            "source_type",
            "latest_error",
            "last_run_at",
            "schemas",
            "engine",
            "revenue_analytics_config",
            "user_access_level",
            "access_method",
            "supports_webhooks",
            "supports_column_selection",
        ]

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        job_inputs = representation.get("job_inputs", {})
        if not isinstance(job_inputs, dict):
            return representation

        # Derive allowed keys dynamically from source config field definitions
        try:
            source_type_model = ExternalDataSourceType(instance.source_type)
            source = SourceRegistry.get_source(source_type_model)
            nonsensitive, sensitive = get_nonsensitive_and_sensitive_field_names(source.get_source_config.fields)
            # CDC fields aren't form fields but are non-secret operational config the UI needs.
            nonsensitive = nonsensitive | _CDC_EXPOSED_JOB_INPUT_KEYS
        except (ValueError, KeyError):
            representation["job_inputs"] = {}
            return representation

        # Normalize SSH tunnel legacy format before stripping
        if "ssh_tunnel" in job_inputs and isinstance(job_inputs["ssh_tunnel"], dict):
            tunnel = job_inputs["ssh_tunnel"]
            # Normalize 'auth_type' (legacy from migration 0807) -> 'auth'
            if "auth_type" in tunnel and "auth" not in tunnel:
                tunnel["auth"] = tunnel.pop("auth_type")
            if isinstance(tunnel.get("auth"), dict):
                auth = tunnel["auth"]
                # Normalize 'type' (legacy) -> 'selection'
                if "type" in auth and "selection" not in auth:
                    auth["selection"] = auth.pop("type")
            # Backfill require_tls default for sources created before the toggle existed
            if "require_tls" not in tunnel:
                tunnel["require_tls"] = {"enabled": True}

        representation["job_inputs"] = strip_sensitive_from_dict(job_inputs, nonsensitive, sensitive)
        return representation

    def get_last_run_at(self, instance: ExternalDataSource) -> str | None:
        latest_completed_run = instance.ordered_jobs[0] if instance.ordered_jobs else None  # type: ignore

        return latest_completed_run.created_at.isoformat() if latest_completed_run else None

    def get_created_by(self, instance: ExternalDataSource) -> str | None:
        return instance.created_by.email if instance.created_by else None

    def get_supports_webhooks(self, instance: ExternalDataSource) -> bool:
        try:
            source = SourceRegistry.get_source(ExternalDataSourceType(instance.source_type))
            return isinstance(source, WebhookSource)
        except Exception as e:
            capture_exception(e)
            return False

    def get_supports_column_selection(self, instance: ExternalDataSource) -> bool:
        return source_supports_column_selection(instance.source_type)

    def get_status(self, instance: ExternalDataSource) -> str:
        active_schemas: list[ExternalDataSchema] = list(instance.active_schemas)  # type: ignore
        # Negative statuses should ignore schemas the user has disabled — those can linger in
        # active_schemas via the latest_error prefetch but shouldn't drag the source into a failed state.
        syncing_schemas = [schema for schema in active_schemas if schema.should_sync]
        any_failures = any(schema.status == ExternalDataSchema.Status.FAILED for schema in syncing_schemas)
        any_billing_limits_reached = any(
            schema.status == ExternalDataSchema.Status.BILLING_LIMIT_REACHED for schema in syncing_schemas
        )
        any_billing_limits_too_low = any(
            schema.status == ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW for schema in syncing_schemas
        )
        any_paused = any(schema.status == ExternalDataSchema.Status.PAUSED for schema in active_schemas)
        any_running = any(schema.status == ExternalDataSchema.Status.RUNNING for schema in active_schemas)
        any_completed = any(schema.status == ExternalDataSchema.Status.COMPLETED for schema in active_schemas)

        if any_failures:
            return ExternalDataSchema.Status.FAILED
        elif any_billing_limits_reached:
            return "Billing limits"
        elif any_billing_limits_too_low:
            return "Billing limits too low"
        elif any_paused:
            return ExternalDataSchema.Status.PAUSED
        elif any_running:
            return ExternalDataSchema.Status.RUNNING
        elif any_completed:
            return ExternalDataSchema.Status.COMPLETED
        else:
            # Fallback during migration phase of going from source -> schema as the source of truth for syncs
            return instance.status

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_latest_error(self, instance: ExternalDataSource):
        prefetched_schemas = getattr(instance, "_prefetched_objects_cache", {}).get("schemas")
        if prefetched_schemas is not None:
            schema_with_error = next(
                (schema for schema in prefetched_schemas if not schema.deleted and schema.latest_error is not None),
                None,
            )
        else:
            schema_with_error = instance.schemas.filter(latest_error__isnull=False).first()
        return schema_with_error.latest_error if schema_with_error else None

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_schemas(self, instance: ExternalDataSource):
        prefetched_schemas = getattr(instance, "_prefetched_objects_cache", {}).get("schemas")
        if prefetched_schemas is not None:
            schemas = [schema for schema in prefetched_schemas if not schema.deleted]
        else:
            schemas = list(instance.schemas.exclude(deleted=True).order_by("name"))
        return ExternalDataSchemaSerializer(schemas, many=True, read_only=True, context=self.context).data

    def update(self, instance: ExternalDataSource, validated_data: Any) -> Any:
        request = self.context.get("request")
        requested_access_method = request.data.get("access_method") if request is not None else None
        if requested_access_method is not None and requested_access_method != instance.access_method:
            raise ValidationError("Access method cannot be changed. Create a new source instead.")

        validated_data.pop("access_method", None)
        # created_via is set at creation time and cannot be mutated afterwards
        validated_data.pop("created_via", None)
        incoming_prefix = validated_data.get("prefix", instance.prefix)

        if instance.is_direct_query:
            # For direct query sources the prefix acts as the user-facing source name.
            normalized_prefix = incoming_prefix.strip() if isinstance(incoming_prefix, str) else ""
            if not normalized_prefix:
                raise ValidationError("Name is required for direct query sources")
            validated_data["prefix"] = normalized_prefix
        else:
            validated_data["prefix"] = instance.prefix

        existing_job_inputs = instance.job_inputs or {}
        job_inputs_were_submitted = "job_inputs" in validated_data
        incoming_job_inputs = validated_data.get("job_inputs", {})

        source_type_model = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type_model)
        sensitive_fields = get_sensitive_field_names(source.get_source_config.fields)
        discovered_schemas: list[SourceSchema] | None = None

        new_job_inputs = {**existing_job_inputs, **incoming_job_inputs}

        # CDC resource ownership changes must go through the CDC-specific endpoints.
        for key in _CDC_EXPOSED_JOB_INPUT_KEYS:
            if key in existing_job_inputs:
                new_job_inputs[key] = existing_job_inputs[key]
            else:
                new_job_inputs.pop(key, None)

        # The OAuth2 integration row pointer is server-managed: pin it to the stored value so an
        # editor can't repoint the source at a different row (and through it, different credentials).
        # Re-entered auth_oauth2_* secrets flow into the pinned row during credential validation.
        if source_type_model == ExternalDataSourceType.CUSTOM:
            existing_oauth2_pointer = existing_job_inputs.get("auth_oauth2_integration_id")
            if existing_oauth2_pointer:
                new_job_inputs["auth_oauth2_integration_id"] = existing_oauth2_pointer
            else:
                new_job_inputs.pop("auth_oauth2_integration_id", None)

        # If the connection target changed, require credentials to be re-entered. Covers
        # both the generic `host` field and source-specific URL fields like ServiceNow's
        # `instance_url`, so a stored credential can't be redirected to a new host.
        connection_host_changed = any(
            field in incoming_job_inputs and incoming_job_inputs[field] != existing_job_inputs.get(field)
            for field in _CONNECTION_TARGET_FIELDS
        )

        # Some sources keep their connection target in a differently named field (e.g. Okta's
        # `okta_domain`, Freshdesk's `subdomain`). Changing one would send the preserved credential
        # to a new host — the same exfiltration risk as a `host` change — so require re-entry too.
        connection_host_changed = connection_host_changed or any(
            field in incoming_job_inputs and incoming_job_inputs[field] != existing_job_inputs.get(field)
            for field in source.connection_host_fields
        )

        # If the SSH tunnel's connection target changed, also require credentials. Without this an
        # editor could swap in a tunnel that routes the backend's auth to an attacker-controlled
        # server, exfiltrating the stored database credentials (VERIA-311).
        ssh_tunnel_changed = "ssh_tunnel" in incoming_job_inputs and ssh_tunnel_connection_changed(
            existing_job_inputs.get("ssh_tunnel"),
            incoming_job_inputs.get("ssh_tunnel"),
        )

        # The custom source's connection target lives inside the manifest, not a top-level `host`.
        # A manifest edit that introduces a new request host would send the preserved credential
        # somewhere it wasn't going before — the same exfiltration risk, so require re-entry too.
        manifest_host_added = False
        if source_type_model == ExternalDataSourceType.CUSTOM and "manifest_json" in incoming_job_inputs:
            new_hosts = manifest_request_hosts(incoming_job_inputs.get("manifest_json"))
            existing_hosts = manifest_request_hosts(existing_job_inputs.get("manifest_json"))
            manifest_host_added = bool(new_hosts - existing_hosts)

        # A row-backed OAuth2 custom source carries no secret in job_inputs — the client secret +
        # tokens live in the bound CustomOAuth2Integration row and are injected at sync time. So
        # `has_preserved_credentials` never sees a preserved secret for it, yet a host change would
        # still redirect the row's injected token to the new host. Re-entering every secret the row
        # holds satisfies the gate the same way typing a password does for other sources: because a
        # config change makes adoption replace the row's secrets with the typed ones outright (see
        # _apply_oauth2_material — the rotated-token keep-rule is suspended on config change), only
        # material the editor provably possesses is ever sent to the new host.
        bound_integration = None
        if source_type_model == ExternalDataSourceType.CUSTOM:
            bound_integration = (
                CustomOAuth2Integration.objects.for_team(instance.team_id).filter(external_data_source=instance).first()
            )
        reentered_oauth2_secrets = False
        if bound_integration is not None:
            held_secret_fields = [
                incoming_field
                for row_key, incoming_field in (
                    ("client_secret", "auth_oauth2_client_secret"),
                    ("refresh_token", "auth_oauth2_refresh_token"),
                )
                if bound_integration.sensitive_config.get(row_key)
            ]
            reentered_oauth2_secrets = bool(held_secret_fields) and all(
                bool(incoming_job_inputs.get(field)) for field in held_secret_fields
            )
        preserved_oauth2_integration = bound_integration is not None and not reentered_oauth2_secrets

        if connection_host_changed or ssh_tunnel_changed or manifest_host_added:
            gate_sensitive_fields = sensitive_fields - _CREATION_ONLY_SECRET_FIELDS
            preserved_credentials = has_preserved_credentials(
                existing_job_inputs, incoming_job_inputs, gate_sensitive_fields
            )
            if preserved_credentials or preserved_oauth2_integration:
                if ssh_tunnel_changed:
                    raise ValidationError("Changing the SSH tunnel requires re-entering your database credentials.")
                if manifest_host_added:
                    raise ValidationError("Changing the manifest's request host requires re-entering your credentials.")
                raise ValidationError("Changing the connection host requires re-entering your credentials.")

        # Preserve sensitive credentials not explicitly provided (API response omits them for security)
        for key in sensitive_fields:
            if existing_job_inputs.get(key) and not incoming_job_inputs.get(key):
                new_job_inputs[key] = existing_job_inputs[key]

        # SSH tunnel is a nested config - deep-merge it so partial updates preserve existing fields
        existing_ssh_tunnel = existing_job_inputs.get("ssh_tunnel")

        # Nested SourceFieldSelectConfig containers (e.g. Stripe `auth_method`, Snowflake `auth_type`) need
        # a deep-merge that preserves sensitive fields not explicitly provided. The shallow merge above
        # would otherwise wipe redacted credentials nested inside these containers.
        for container_key in ("auth_method", "auth_type"):
            existing_container = existing_job_inputs.get(container_key)
            incoming_container = incoming_job_inputs.get(container_key)
            if incoming_container is not None and not isinstance(incoming_container, dict):
                raise ValidationError({"job_inputs": {container_key: "Must be an object."}})
            if not (isinstance(existing_container, dict) and isinstance(incoming_container, dict)):
                continue
            selection_changed = existing_container.get("selection") != incoming_container.get("selection")
            if selection_changed:
                # Selection switched (e.g. password→keypair) — use only incoming, don't carry over old secrets
                new_job_inputs[container_key] = incoming_container
            else:
                merged_container = {**existing_container, **incoming_container}
                for key in sensitive_fields:
                    if existing_container.get(key) and not incoming_container.get(key):
                        merged_container[key] = existing_container[key]
                new_job_inputs[container_key] = merged_container

        incoming_ssh_tunnel = incoming_job_inputs.get("ssh_tunnel")
        if existing_ssh_tunnel and incoming_ssh_tunnel is not None:
            ssh_tunnel_host_changed = "host" in incoming_ssh_tunnel and incoming_ssh_tunnel[
                "host"
            ] != existing_ssh_tunnel.get("host")

            # Deep-merge: start with existing, overlay incoming top-level keys
            merged_ssh_tunnel = {**existing_ssh_tunnel, **incoming_ssh_tunnel}

            # Check both 'auth' (new format) and 'auth_type' (legacy format from migration 0807)
            existing_auth = (
                (existing_ssh_tunnel or {}).get("auth") or (existing_ssh_tunnel or {}).get("auth_type") or {}
            )
            incoming_auth = (
                (incoming_ssh_tunnel or {}).get("auth") or (incoming_ssh_tunnel or {}).get("auth_type") or {}
            )

            if ssh_tunnel_host_changed and not incoming_auth:
                raise ValidationError("Changing the SSH tunnel host requires re-entering your SSH credentials.")

            if not incoming_auth:
                # No auth in incoming request - preserve entire existing auth
                merged_ssh_tunnel["auth"] = {**existing_auth}
            else:
                # Merge auth, preserving sensitive fields not explicitly provided
                merged_auth = {**incoming_auth}
                if not ssh_tunnel_host_changed:
                    for key in ("password", "passphrase", "private_key"):
                        if existing_auth.get(key) and not incoming_auth.get(key):
                            merged_auth[key] = existing_auth[key]
                merged_ssh_tunnel["auth"] = merged_auth

            new_job_inputs["ssh_tunnel"] = merged_ssh_tunnel

        is_valid, errors = source.validate_config(new_job_inputs)
        if not is_valid:
            raise ValidationError(f"Invalid source config: {', '.join(errors)}")

        # Clearing a multi-schema source's namespace migrates legacy rows to qualified naming.
        old_schema = detect_sql_schema_clear_transition(
            source_type=instance.source_type,
            existing_job_inputs=existing_job_inputs,
            incoming_job_inputs=incoming_job_inputs,
        )
        if old_schema is not None:
            apply_sql_warehouse_schema_clear_migration(instance, old_schema)

        source_config: Config = source.parse_config(new_job_inputs)
        validated_job_inputs = source_config.to_dict()
        for key in _CDC_EXPOSED_JOB_INPUT_KEYS:
            if key in existing_job_inputs:
                validated_job_inputs[key] = existing_job_inputs[key]
        validated_data["job_inputs"] = validated_job_inputs

        if job_inputs_were_submitted:
            if isinstance(source, (PostgresSource, MySQLSource)):
                credentials_valid, credentials_error = source.validate_credentials_for_access_method(
                    cast(Any, source_config), instance.team_id, instance.access_method
                )
            elif isinstance(source, CustomSource):
                # Pass the source being updated so an integration-backed OAuth2 source can only validate
                # with the integration bound to it — not another source's, whose token the probe would
                # otherwise mint and send to the submitted manifest host. owner_user_id additionally gates
                # an as-yet-unbound integration to its creator.
                credentials_valid, credentials_error = source.validate_credentials(
                    source_config,
                    instance.team_id,
                    source_id=str(instance.pk),
                    owner_user_id=self.context["request"].user.id,
                )
            else:
                credentials_valid, credentials_error = source.validate_credentials(source_config, instance.team_id)
            if not credentials_valid:
                raise ValidationError(credentials_error or "Invalid credentials")
            if instance.is_direct_query:
                discovered_schemas = source.get_schemas(source_config, instance.team_id)
                validated_data["connection_metadata"] = get_direct_connection_metadata(
                    source_impl=source,
                    source_config=source_config,
                    team_id=instance.team_id,
                    source_model=instance,
                    fallback=instance.connection_metadata,
                )

        if job_inputs_were_submitted and isinstance(source, CustomSource):
            # Credential validation adopts re-entered OAuth2 secrets into the integration row and
            # rewrites the config (pointer set, static secrets cleared) — re-serialize so job_inputs
            # stores the pointer and never the raw secrets.
            validated_job_inputs = source_config.to_dict()
            for key in _CDC_EXPOSED_JOB_INPUT_KEYS:
                if key in existing_job_inputs:
                    validated_job_inputs[key] = existing_job_inputs[key]
            validated_data["job_inputs"] = validated_job_inputs

        updated_source: ExternalDataSource = super().update(instance, validated_data)

        if updated_source.is_direct_query and discovered_schemas is not None:
            schema_names = {schema.name: schema.label for schema in discovered_schemas}
            descriptions = {schema.name: schema.description for schema in discovered_schemas}

            with transaction.atomic():
                ExternalDataSource._base_manager.filter(pk=updated_source.pk).select_for_update().get()
                name_substitutions: dict[str, str] = {}
                if updated_source.source_type == ExternalDataSourceType.POSTGRES:
                    name_substitutions = reconcile_postgres_refresh_name_substitutions(
                        source=updated_source,
                        source_schemas=discovered_schemas,
                        team_id=instance.team_id,
                    )
                elif source_namespace_is_blank(updated_source) and is_multi_schema_capable_sql_source(
                    updated_source.source_type
                ):
                    name_substitutions = apply_sql_warehouse_refresh_migration(
                        source=updated_source,
                        team_id=instance.team_id,
                    )
                if name_substitutions:
                    schema_names = {name_substitutions.get(name, name): label for name, label in schema_names.items()}
                    descriptions = {
                        name_substitutions.get(name, name): description for name, description in descriptions.items()
                    }
                sync_old_schemas_with_new_schemas(
                    schema_names,
                    source_id=str(updated_source.id),
                    team_id=instance.team_id,
                    descriptions=descriptions,
                )
                # Direct call (not via hook) so tests mocking `SourceRegistry.get_source` still
                # exercise the real direct-query DataWarehouseTable rebuild.
                if updated_source.source_type == ExternalDataSourceType.POSTGRES:
                    reconcile_postgres_schemas(
                        source=updated_source,
                        source_schemas=discovered_schemas,
                        team_id=instance.team_id,
                    )
                elif updated_source.source_type == ExternalDataSourceType.SNOWFLAKE:
                    reconcile_snowflake_schemas(
                        source=updated_source,
                        source_schemas=discovered_schemas,
                        team_id=instance.team_id,
                    )
                else:
                    reconcile_mysql_schemas(
                        source=updated_source,
                        source_schemas=discovered_schemas,
                        team_id=instance.team_id,
                    )

            schemas = list(
                ExternalDataSchema.objects.filter(team_id=instance.team_id, source_id=updated_source.id)
                .exclude(deleted=True)
                .select_related("table__credential", "table__external_data_source")
                .order_by("name")
            )
            active_schemas = list(
                ExternalDataSchema.objects.filter(team_id=instance.team_id, source_id=updated_source.id)
                .exclude(deleted=True)
                .filter(Q(should_sync=True) | Q(latest_error__isnull=False))
                .select_related("source", "table__credential", "table__external_data_source")
            )
            updated_source_any = cast(Any, updated_source)
            updated_source_any._prefetched_objects_cache = {"schemas": schemas}
            updated_source_any.active_schemas = active_schemas

        return updated_source


class ExternalDataSourceCreateSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type (e.g. 'Postgres', 'Stripe').",
    )
    payload = serializers.DictField(
        help_text="Connection credentials and a 'schemas' array. Keys depend on source_type.",
    )
    prefix = serializers.CharField(
        max_length=100, required=False, allow_null=True, allow_blank=True, help_text="Table name prefix in HogQL."
    )
    description = serializers.CharField(
        max_length=400, required=False, allow_null=True, allow_blank=True, help_text="Human-readable description."
    )
    access_method = serializers.ChoiceField(
        choices=ExternalDataSource.AccessMethod.choices,
        required=False,
        default=ExternalDataSource.AccessMethod.WAREHOUSE,
        help_text="Connection mode: 'warehouse' (import) or 'direct' (live query).",
    )
    created_via = serializers.ChoiceField(
        choices=ExternalDataSource.CreatedVia.values,
        required=False,
        default=ExternalDataSource.CreatedVia.API,
        help_text="Where the request came from",
    )
    direct_query_enabled = serializers.BooleanField(
        required=False,
        default=True,
        help_text=(
            "Whether a synced source should also be live-queryable via direct connection. "
            "Defaults to true; ignored for pure direct-query sources."
        ),
    )


class SourceSetupSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type to set up (e.g. 'Stripe', 'Postgres', 'Hubspot').",
    )
    payload = serializers.DictField(
        required=False,
        help_text=(
            "Connection details as flat keys for the source_type (discover required fields with the wizard "
            "tool). Prefer references over raw secrets: pass {'credential_id': <id>} referencing the connection "
            "details the user stored via the connect-link page (discover ids with the stored_credentials "
            "endpoint) — they are merged in server-side and deleted once consumed. An already-connected OAuth "
            "integration can be passed via its id key instead (e.g. {'hubspot_integration_id': 123}). "
            "For source_type 'Custom' (a user-defined REST API) the keys are 'manifest_json' (a stringified "
            "RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the auth "
            "type the manifest declares — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' "
            "(http_basic); keep secrets in these auth_* keys, never inline in the manifest. "
            "A 'schemas' array is NOT required — all discovered tables are enabled automatically with sensible "
            "sync defaults."
        ),
    )
    prefix = serializers.CharField(
        max_length=100,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Table name prefix in HogQL, e.g. 'stripe' produces stripe_charges. Defaults to the source type.",
    )
    description = serializers.CharField(
        max_length=400, required=False, allow_null=True, allow_blank=True, help_text="Human-readable description."
    )
    direct_query_enabled = serializers.BooleanField(
        required=False,
        default=True,
        help_text=(
            "Whether a synced source should also be live-queryable via direct connection. "
            "Defaults to true; ignored for pure direct-query sources."
        ),
    )


class SourceSetupWebhookSerializer(serializers.Serializer):
    success = serializers.BooleanField(
        help_text=(
            "Whether the webhook was registered with the external service. When true, webhook-capable tables "
            "(including webhook-only ones) sync via real-time webhooks; when false, tables fall back to the "
            "polling sync defaults and webhook-only tables stay disabled."
        )
    )
    webhook_url = serializers.CharField(
        allow_null=True, help_text="The PostHog endpoint the external service delivers events to."
    )
    error = serializers.CharField(
        allow_null=True, help_text="Why webhook registration failed (e.g. the credentials lack webhook permissions)."
    )
    pending_inputs = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "Webhook input names the user still needs to provide (e.g. a signing secret the external API did not "
            "return on create). Submit them via the update_webhook_inputs endpoint."
        ),
    )


class SourceSetupResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the created external data source.")
    webhook = SourceSetupWebhookSerializer(
        required=False,
        help_text=(
            "Outcome of automatic webhook registration. Only present for sources that support webhooks "
            "(e.g. Stripe) and have webhook-capable tables."
        ),
    )


class SourceConnectLinkSerializer(serializers.Serializer):
    source_type = serializers.CharField(help_text="The source type the link is for.")
    auth_method = serializers.ChoiceField(
        choices=["oauth", "credentials"],
        help_text=(
            "What the user will do on the connect page: 'oauth' = authorize an account in their browser; "
            "'credentials' = enter connection details (or pick OAuth where the source offers both). Either "
            "way secrets never pass through the agent, and the result is always a stored credential id."
        ),
    )
    connect_url = serializers.CharField(
        help_text=(
            "Full URL to share with the user. It opens the source's connection form in PostHog — "
            "credentials never pass through the agent or the chat."
        )
    )
    instructions = serializers.CharField(help_text="Next steps for the agent to relay to the user.")


class SourceCredentialCreateSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type these credentials are for (e.g. 'Stripe', 'Postgres').",
    )
    payload = serializers.DictField(
        help_text=(
            "Connection details as flat keys for the source_type — the same fields the create flow accepts "
            "(host, port, password, API key, …). Checked against a live connection before being stored."
        ),
    )


class SourceCredentialSerializer(serializers.Serializer):
    credential_id = serializers.UUIDField(
        help_text="Stored credential id. Pass to the setup endpoint as {'credential_id': <id>} to create the source."
    )
    source_type = serializers.CharField(help_text="The source type the stored credentials are for.")
    created_at = serializers.DateTimeField(help_text="When the credentials were stored.")
    expires_at = serializers.DateTimeField(
        help_text="When the stored credentials expire. Unconsumed credentials are unusable past this time."
    )


def _find_unresolved_secret_refs(payload: Any) -> list[str]:
    """Return payload keys whose value is an unresolved secret reference.

    The wizard CLI's `wizard_ask` returns sensitive answers as `{"secretRef": "..."}` objects that the
    caller must resolve to real values before they reach PostHog. If one slips through, source creation
    fails downstream with a confusing "invalid credentials"/"invalid API key" error — detect it up front
    so the agent gets an actionable message instead.
    """
    if not isinstance(payload, dict):
        return []
    return [key for key, value in payload.items() if isinstance(value, dict) and "secretRef" in value]


def _unresolved_secret_ref_response(payload: Any) -> Response | None:
    offenders = _find_unresolved_secret_refs(payload)
    if not offenders:
        return None
    return Response(
        status=status.HTTP_400_BAD_REQUEST,
        data={
            "message": (
                f"Unresolved secret reference(s) for: {', '.join(sorted(offenders))}. These fields are still "
                "`{'secretRef': ...}` objects — PostHog cannot resolve them. Resolve the secret to its real "
                "value before calling (or collect credentials via data-warehouse-source-connect-link and pass "
                "the resulting credential_id instead)."
            )
        },
    )


def _find_top_level_oauth_field(config: dict) -> dict | None:
    """Find a top-level OAuth field ({type: 'oauth', kind, name, ...}) in a source config dump.

    Only a top-level OAuth field makes a source OAuth-only (e.g. Hubspot). An OAuth option
    nested inside a select (e.g. Stripe's auth_method) coexists with credential options, so
    those sources route to the credentials connect page — its form still offers the OAuth
    choice alongside API keys.
    """
    for field in config.get("fields") or []:
        if isinstance(field, dict) and field.get("type") == "oauth" and field.get("kind"):
            return field
    return None


class DatabaseSchemaRequestSerializer(serializers.Serializer):
    """Validate credentials and preview available tables from a remote database.

    The request body contains source_type plus flat source-specific credential fields
    (e.g. host, port, database, user, password, schema for Postgres). The credential
    fields vary per source_type and are validated dynamically by the source registry.

    For source_type "Custom" (a user-defined REST API) the body carries `manifest_json`
    (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the
    credential for the manifest's declared auth type — `auth_token` (bearer), `auth_api_key`
    (api_key), or `auth_password` (http_basic); keep secrets in these auth_* keys, never
    inline in manifest_json. The returned tables mirror the manifest's resources, with
    detected primary keys and incremental cursors.
    """

    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type to validate against.",
    )


class SourcePreviewRequestSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type to preview. Only 'Custom' (a user-defined REST API) is supported today.",
    )
    payload = serializers.DictField(
        required=False,
        help_text=(
            "Source config as flat keys. For source_type 'Custom': 'manifest_json' (a stringified RESTAPIConfig "
            "describing client.base_url, auth, and resources) plus the credential for the manifest's declared auth "
            "type — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic). Secrets stay "
            "in these auth_* keys, never inline in the manifest."
        ),
    )
    resource_name = serializers.CharField(
        help_text="Which manifest resource (table) to read a sample from — one of the resource names in manifest_json.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=PREVIEW_DEFAULT_ROWS,
        min_value=1,
        max_value=PREVIEW_MAX_ROWS,
        help_text=f"Maximum sample rows to return (1–{PREVIEW_MAX_ROWS}). Defaults to {PREVIEW_DEFAULT_ROWS}.",
    )


class SourcePreviewColumnSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Column name as it appears in the previewed rows.")
    type = serializers.CharField(
        help_text="JSON type inferred from the first non-null value: string, integer, number, boolean, object, array, or null."
    )


class SourcePreviewResponseSerializer(serializers.Serializer):
    rows = serializers.ListField(
        child=serializers.DictField(),
        help_text="Up to `limit` sample rows, after data_selector extraction — the raw records the sync would ingest.",
    )
    row_count = serializers.IntegerField(help_text="Number of sample rows returned (≤ limit).")
    columns = SourcePreviewColumnSerializer(
        many=True,
        help_text="Columns observed across the sample rows, each with an inferred JSON type.",
    )
    error = serializers.CharField(
        allow_null=True,
        help_text=(
            "Set when the live read failed (e.g. the host was unreachable or returned an auth error); rows is then "
            "empty. Manifest, validation, and SSRF problems return HTTP 400 instead of populating this field."
        ),
    )


class DraftCustomManifestRequestSerializer(serializers.Serializer):
    source_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional human name of the API being connected (e.g. 'Acme CRM'). Used only to orient the model.",
    )
    docs_url = serializers.URLField(
        required=False,
        allow_blank=True,
        help_text="URL of the API documentation to read. Provide this or docs_text; fetched server-side via the egress proxy.",
    )
    docs_text = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Raw API documentation or an OpenAPI/Swagger spec, pasted directly. Provide this or docs_url.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Strip first: a whitespace-only docs_text is truthy but useless (it'd fetch an empty URL).
        if not ((attrs.get("docs_url") or "").strip() or (attrs.get("docs_text") or "").strip()):
            raise serializers.ValidationError("Provide either docs_url or docs_text.")
        return attrs


class DraftCustomManifestResponseSerializer(serializers.Serializer):
    draft_status = serializers.ChoiceField(
        choices=["ok", "invalid", "model_error"],
        help_text=(
            "'ok' = a manifest validated; 'invalid' = a manifest was drafted but never validated within the budget "
            "(see error; manifest_json holds the last attempt to fix by hand); 'model_error' = the model returned no "
            "usable JSON."
        ),
    )
    manifest_json = serializers.CharField(
        allow_null=True,
        help_text="The drafted RESTAPIConfig manifest as a JSON string (non-secret), or null if none was produced.",
    )
    resource_names = serializers.ListField(
        child=serializers.CharField(),
        help_text="Names of the resources (tables) the validated manifest exposes. Empty unless draft_status is 'ok'.",
    )
    attempts = serializers.IntegerField(
        help_text="How many draft→validate→repair rounds were run.",
    )
    error = serializers.CharField(
        allow_null=True,
        help_text="The last validation error when draft_status is not 'ok'; null on success.",
    )


class SimpleExternalDataSourceSerializers(serializers.ModelSerializer):
    class Meta:
        model = ExternalDataSource
        fields = [
            "id",
            "created_at",
            "created_by",
            "status",
            "source_type",
        ]
        read_only_fields = ["id", "created_by", "created_at", "status", "source_type"]


@extend_schema(extensions={"x-product": "warehouse_sources"})
class ExternalDataSourceViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete External data Sources.
    """

    scope_object = "external_data_source"
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "reload",
        "refresh_schemas",
        "database_schema",
        "setup",
        "store_credentials",
        "source_prefix",
        "revenue_analytics_config",
        "create_webhook",
        "update_webhook_inputs",
        "delete_webhook",
        "check_cdc_prerequisites",
        "check_cdc_prerequisites_for_source",
        "enable_cdc",
        "disable_cdc",
        "update_cdc_settings",
        # Live outbound HTTP to a caller-supplied manifest (including POSTs) — a
        # side-effecting action, so it needs write scope, not read.
        "preview_resource",
        # Fetches a caller-supplied docs URL and calls the (paid) LLM gateway — side-effecting.
        "draft_custom_manifest",
    ]
    scope_object_read_actions = [
        "list",
        "retrieve",
        "jobs",
        "wizard",
        "connect_link",
        "stored_credentials",
        "webhook_info",
        "connections",
        "cdc_status",
    ]
    queryset = ExternalDataSource.objects.all()
    serializer_class = ExternalDataSourceSerializers
    filter_backends = [filters.SearchFilter]
    # `source_id` is an opaque internal connection UUID — useless to search by. Callers
    # (the in-app sources list, the MCP tool) narrow by what they can actually see: the
    # source type ("Stripe", "Postgres") and the HogQL table prefix.
    search_fields = ["source_type", "prefix"]
    ordering = "-created_at"

    def get_throttles(self):
        # The AI manifest builder fans out to several Opus calls per request and isn't billed to the
        # customer, so cap it per team: a burst guard against double-submits/retries, an hourly window
        # for an intense setup session, and a daily backstop against scripted abuse.
        if self.action == "draft_custom_manifest":
            return [
                CustomSourceAIBuilderBurstThrottle(),
                CustomSourceAIBuilderSustainedThrottle(),
                CustomSourceAIBuilderDailyThrottle(),
            ]
        return super().get_throttles()

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.action == "create":
            return ExternalDataSourceCreateSerializer
        if self.action == "database_schema":
            return DatabaseSchemaRequestSerializer
        return ExternalDataSourceSerializers

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        # Building the full HogQL Database and serializing per-schema table columns is expensive
        # and only needed when a caller reads `schemas[].table.columns` — which the source list view
        # never does (it only reads name/row_count). Gate both to single-source reads.
        include_columns = self.action != "list"
        context["include_columns"] = include_columns
        if include_columns:
            context["database"] = Database.create_for(team_id=self.team_id, user=cast(User, self.request.user))

        return context

    def safely_get_queryset(self, queryset):
        return (
            queryset.exclude(deleted=True)
            .prefetch_related(
                "created_by",
                Prefetch(
                    "jobs",
                    queryset=ExternalDataJob.objects.filter(status="Completed", team_id=self.team_id).order_by(
                        "-created_at"
                    )[:1],
                    to_attr="ordered_jobs",
                ),
                Prefetch(
                    "schemas",
                    queryset=ExternalDataSchema.objects.filter(team_id=self.team_id)
                    .exclude(deleted=True)
                    .select_related("table__credential", "table__external_data_source")
                    .order_by("name"),
                ),
                Prefetch(
                    "schemas",
                    queryset=ExternalDataSchema.objects.filter(team_id=self.team_id)
                    .exclude(deleted=True)
                    .filter(
                        Q(should_sync=True) | Q(latest_error__isnull=False)
                    )  # OR to include schemas with errors or marked for sync
                    .select_related("source", "table__credential", "table__external_data_source"),
                    to_attr="active_schemas",
                ),
            )
            .order_by(self.ordering)
        )

    @extend_schema(request=ExternalDataSourceCreateSerializer, responses=ExternalDataSourceSerializers)
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        secret_ref_response = _unresolved_secret_ref_response(serializer.validated_data["payload"])
        if secret_ref_response is not None:
            return secret_ref_response

        return self._create_external_data_source(
            request,
            source_type=serializer.validated_data["source_type"],
            payload=serializer.validated_data["payload"],
            prefix=serializer.validated_data.get("prefix"),
            description=serializer.validated_data.get("description"),
            access_method=serializer.validated_data.get("access_method", ExternalDataSource.AccessMethod.WAREHOUSE),
            created_via=serializer.validated_data.get("created_via", ExternalDataSource.CreatedVia.API),
            direct_query_enabled=serializer.validated_data.get("direct_query_enabled", True),
        )

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        # Runs for both PUT and PATCH (DRF's partial_update delegates to update -> perform_update).
        # `created_via` is write-once and reflects original creation origin; the edit's own origin
        # comes from the request-derived `source` that report_user_action attaches.
        super().perform_update(serializer)
        instance = cast(ExternalDataSource, serializer.instance)
        report_user_action(
            cast(User, self.request.user),
            "data warehouse source updated",
            {
                "source_type": instance.source_type,
                "created_via": instance.created_via,
                "source_id": str(instance.pk),
            },
            team=self.team,
            request=self.request,
        )

    def _create_external_data_source(
        self,
        request: Request,
        *,
        source_type: str,
        payload: dict,
        prefix: str | None,
        description: str | None,
        access_method: str,
        created_via: str,
        direct_query_enabled: bool = True,
        skip_credential_validation: bool = False,
    ) -> Response:
        # `skip_credential_validation` is set only by the `setup` action, which has already run the
        # full config + credential gate (including the SSRF host check) before discovering schemas.
        # It avoids a second live credential round-trip — and the confusing failure mode where the
        # first check passes but a transient blip fails the second, leaving nothing created.
        is_direct_query = access_method == ExternalDataSource.AccessMethod.DIRECT
        is_direct_mysql = is_direct_query and source_type == ExternalDataSourceType.MYSQL
        is_direct_snowflake = is_direct_query and source_type == ExternalDataSourceType.SNOWFLAKE

        if is_direct_query and source_type not in direct_capable_source_types():
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": DIRECT_QUERY_UNSUPPORTED_SOURCE_MESSAGE},
            )

        if is_direct_query:
            prefix = prefix.strip() if isinstance(prefix, str) else ""
            if not prefix:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Name is required for direct query sources"},
                )
        else:
            is_valid, error_message = validate_source_prefix(prefix)
            if not is_valid:
                raise ValidationError(error_message)

            if not prefix:
                if self.prefix_required(source_type):
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": "Source type already exists. Prefix is required"},
                    )
            elif self.prefix_exists(source_type, prefix):
                return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Prefix already exists"})

        if access_method == ExternalDataSource.AccessMethod.WAREHOUSE and is_any_external_data_schema_paused(
            self.team_id
        ):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please increase your billing limit to resume syncing."},
            )

        # Strip leading and trailing whitespace
        if payload is not None:
            for key, value in payload.items():
                if isinstance(value, str):
                    payload[key] = value.strip()
        source_type_model = ExternalDataSourceType(source_type)
        if (
            source_type_model == ExternalDataSourceType.CUSTOM
            and count_active_custom_sources(self.team_id) >= MAX_CUSTOM_SOURCES_PER_TEAM
        ):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": CUSTOM_SOURCE_LIMIT_MESSAGE},
            )
        source = SourceRegistry.get_source(source_type_model)
        if skip_credential_validation:
            source_config: Config = source.parse_config(payload)
        else:
            error_response, validated_config = self._validate_source_config_and_credentials(
                source, source_type_model, payload, access_method=access_method
            )
            if error_response is not None or validated_config is None:
                return error_response or Response(status=status.HTTP_400_BAD_REQUEST)
            source_config = validated_config

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            created_by=request.user if isinstance(request.user, User) else None,
            created_via=created_via,
            team=self.team,
            status="Running",
            source_type=source_type_model,
            job_inputs=source_config.to_dict(),
            prefix=prefix,
            description=description,
            access_method=access_method,
            direct_query_enabled=direct_query_enabled,
        )

        if source_type_model == ExternalDataSourceType.CUSTOM:
            # Claim the OAuth2 integration row for the new source right away instead of waiting for the
            # first sync's trust-on-first-use claim, closing the window where another create by the same
            # user (matching the same unbound row) could adopt it. The guarded filter makes a lost race
            # a no-op; sync-time authorization remains the backstop.
            oauth2_integration_id = (new_source_model.job_inputs or {}).get("auth_oauth2_integration_id")
            if oauth2_integration_id:
                CustomOAuth2Integration.objects.for_team(self.team_id).filter(
                    id=oauth2_integration_id, external_data_source__isnull=True
                ).update(external_data_source=new_source_model)

        # CDC: gate per-source-type adapter availability up front so downstream blocks
        # can `if cdc_enabled` without repeating the source-type check.
        try:
            cdc_adapter: CDCSourceAdapter | None = get_cdc_adapter(new_source_model)
        except ValueError:
            cdc_adapter = None
        cdc_enabled = (
            payload.get("cdc_enabled", False) and cdc_adapter is not None and is_cdc_enabled_for_team(self.team)
        )

        source_schemas = source.get_schemas(source_config, self.team_id)
        if is_direct_query:
            new_source_model.connection_metadata = get_direct_connection_metadata(
                source_impl=source,
                source_config=source_config,
                team_id=self.team_id,
                source_model=new_source_model,
            )
            new_source_model.save(update_fields=["connection_metadata", "updated_at"])
        source_schemas_by_name = {schema.name: schema for schema in source_schemas}
        schema_names = [schema.name for schema in source_schemas]
        default_source_schema = source_config.to_dict().get("schema")
        schema_label_by_name = {s.name: s.label for s in source_schemas}

        payload_schemas = payload.get("schemas", None)
        if not payload_schemas or not isinstance(payload_schemas, list):
            new_source_model.delete()
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Schemas not given"},
            )

        # Return 400 if we get any schema names that don't exist in our source
        if any(schema.get("name") not in schema_names for schema in payload_schemas):
            new_source_model.delete()
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Schemas given do not exist in source"},
            )

        # Refuse per-schema `sync_type=cdc` when source-level CDC is off — `_setup_cdc_resources`
        # would be skipped, leaving the source with no replication slot/publication.
        if not cdc_enabled:
            cdc_schemas_in_payload = sorted(
                {
                    schema["name"]
                    for schema in payload_schemas
                    if schema.get("sync_type") == "cdc"
                    and schema.get("should_sync", False)
                    and isinstance(schema.get("name"), str)
                }
            )
            if cdc_schemas_in_payload:
                new_source_model.delete()
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": (
                            "CDC must be enabled on the source before selecting it as a sync type. "
                            f"The following schemas requested CDC: {', '.join(cdc_schemas_in_payload)}."
                        )
                    },
                )

        active_schemas: list[ExternalDataSchema] = []

        # Pre-fetch PK column names for CDC tables
        pk_columns_by_table: dict[str, list[str]] = {}
        if cdc_enabled:
            cdc_table_names_by_schema: dict[str, set[str]] = {}
            cdc_schema_name_by_location: dict[tuple[str, str], str] = {}
            for schema in payload_schemas:
                if schema.get("sync_type") != "cdc" or not schema.get("should_sync", False):
                    continue

                schema_name = schema.get("name")
                if not isinstance(schema_name, str):
                    continue

                _, resolved_source_schema, resolved_source_table_name = get_postgres_source_table_location(
                    schema_name=schema_name,
                    source_schema=source_schemas_by_name.get(schema_name),
                    default_schema=default_source_schema,
                )
                cdc_table_names_by_schema.setdefault(resolved_source_schema, set()).add(resolved_source_table_name)
                cdc_schema_name_by_location[(resolved_source_schema, resolved_source_table_name)] = schema_name

            if cdc_table_names_by_schema:
                try:
                    with cdc_pg_connection(new_source_model) as conn:
                        for db_schema, cdc_table_names in cdc_table_names_by_schema.items():
                            queried_pks = get_primary_key_columns(conn, db_schema, list(cdc_table_names))
                            for table_name, primary_key_columns in queried_pks.items():
                                schema_name = cdc_schema_name_by_location.get((db_schema, table_name))
                                if schema_name is not None:
                                    pk_columns_by_table[schema_name] = primary_key_columns
                except (OperationalError, BaseSSHTunnelForwarderError, SSLRequiredError) as e:
                    # Connecting to the user's database to detect CDC primary keys is expected to
                    # fail when the host, port, credentials, or SSH tunnel are wrong, or the server
                    # requires/refuses SSL. Surface it as a 400, but don't capture it — these are
                    # user/upstream connection problems, not bugs in our code, and capturing every
                    # one floods error tracking. Mirrors the CDC-prerequisite handlers below.
                    new_source_model.delete()
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": f"Could not connect to your database to set up change data capture: {e}"},
                    )

            # CDC needs a PK for UPDATE/DELETE merges. Refuse here so `_setup_cdc_resources` doesn't
            # create replication state on the source for a config we're about to reject.
            tables_missing_pk = sorted(
                {
                    schema["name"]
                    for schema in payload_schemas
                    if schema.get("sync_type") == "cdc"
                    and schema.get("should_sync", False)
                    and isinstance(schema.get("name"), str)
                    and not pk_columns_by_table.get(schema["name"])
                }
            )
            if tables_missing_pk:
                new_source_model.delete()
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": (
                            "CDC requires a primary key on each table. "
                            f"The following tables have no primary key: {', '.join(tables_missing_pk)}."
                        )
                    },
                )

        # Engine-side CDC resource setup runs after PK validation so we don't leave
        # replication state on the source for a config we're about to refuse.
        if cdc_enabled:
            assert cdc_adapter is not None  # narrowed by `cdc_enabled`
            cdc_error = self._setup_cdc_resources(cdc_adapter, new_source_model, payload)
            if cdc_error is not None:
                new_source_model.delete()
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": cdc_error},
                )

        # Create all ExternalDataSchema objects and enable syncing for active schemas
        for schema in payload_schemas:
            sync_type = schema.get("sync_type")
            requires_incremental_fields = sync_type == "incremental" or sync_type == "append"
            incremental_field = schema.get("incremental_field")
            incremental_field_type = schema.get("incremental_field_type")
            primary_key_columns = schema.get("primary_key_columns")
            sync_time_of_day = schema.get("sync_time_of_day")
            should_sync = schema.get("should_sync", False)
            payload_enabled_columns = schema.get("enabled_columns")
            if isinstance(payload_enabled_columns, list):
                # `[]` and `None` are distinct: `None` means sync all columns, `[]` means
                # sync only the always-retained PK + incremental field.
                enabled_columns: list[str] | None = [
                    str(column) for column in payload_enabled_columns if isinstance(column, str)
                ]
            else:
                enabled_columns = None

            payload_row_filters = schema.get("row_filters")
            row_filters: list[dict[str, Any]] | None = (
                payload_row_filters if isinstance(payload_row_filters, list) and payload_row_filters else None
            )

            payload_masked_columns = schema.get("masked_columns")
            masked_columns: list[str] | None = (
                [str(column) for column in payload_masked_columns if isinstance(column, str)]
                if isinstance(payload_masked_columns, list) and payload_masked_columns
                else None
            )

            if should_sync and requires_incremental_fields and incremental_field is None:
                new_source_model.delete()
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Incremental schemas given do not have an incremental field set"},
                )

            if should_sync and requires_incremental_fields and incremental_field_type is None:
                new_source_model.delete()
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Incremental schemas given do not have an incremental field type set"},
                )

            schema_name = schema.get("name")
            source_schema = source_schemas_by_name.get(schema_name)

            metadata_source_catalog: str | None
            metadata_source_schema: str | None
            metadata_source_table_name: str | None
            if source_type_model == ExternalDataSourceType.POSTGRES:
                metadata_source_catalog, metadata_source_schema, metadata_source_table_name = (
                    get_postgres_source_table_location(
                        schema_name=schema_name,
                        source_schema=source_schema,
                        default_schema=default_source_schema,
                    )
                )
            elif is_direct_mysql:
                # Direct mode needs a resolved source location for the live-query table; warehouse
                # mode keeps storing whatever the source reported to avoid changing sync routing.
                metadata_source_catalog = None
                metadata_source_schema, metadata_source_table_name = get_mysql_source_table_location(
                    schema_name=schema_name,
                    source_schema=source_schema,
                    default_schema=default_source_schema or source_config.to_dict().get("database"),
                )
            elif is_direct_snowflake:
                metadata_source_catalog, metadata_source_schema, metadata_source_table_name = (
                    get_snowflake_source_table_location(
                        schema_name=schema_name,
                        source_schema=source_schema,
                        default_schema=default_source_schema,
                        default_catalog=source_config.to_dict().get("database"),
                    )
                )
            else:
                metadata_source_catalog = source_schema.source_catalog if source_schema else None
                metadata_source_schema = source_schema.source_schema if source_schema else None
                metadata_source_table_name = source_schema.source_table_name if source_schema else None

            schema_metadata = (
                sql_schema_metadata(
                    source_schema.columns if source_schema else [],
                    source_schema.foreign_keys if source_schema else [],
                    source_catalog=metadata_source_catalog,
                    source_schema=metadata_source_schema,
                    source_table_name=metadata_source_table_name,
                )
                if source.supports_column_selection
                else {}
            )

            if row_filters is not None:
                # Only sources that push filters into their query (SQL WHERE) can honor them — a
                # saved-but-ignored filter would silently sync unfiltered rows.
                if not source.supports_row_filters:
                    new_source_model.delete()
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={
                            "message": f"Row filter not allowed for schema '{schema_name}': "
                            "row filters are not supported for this source type."
                        },
                    )
                if reason := unsupported_row_filter_reason(
                    is_direct_query=new_source_model.is_direct_query, is_cdc=sync_type == "cdc"
                ):
                    new_source_model.delete()
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": f"Row filter not allowed for schema '{schema_name}': {reason}"},
                    )
                try:
                    validate_and_coerce_row_filters(row_filters, schema_metadata)
                except RowFilterValidationError as e:
                    new_source_model.delete()
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": f"Invalid row filter for schema '{schema_name}': {e}"},
                    )

            is_cdc_schema = sync_type == "cdc"
            # A CDC table the user isn't enabling hasn't been "set up" — leave its sync method
            # blank so the schemas UI prompts the user to configure it before it can sync, rather
            # than presetting `cdc` on every discovered table. Only tables the user actively
            # enables get a concrete CDC method + config.
            cdc_not_set_up = is_cdc_schema and not should_sync
            if requires_incremental_fields and new_source_model.supports_scheduled_sync:
                # If the caller didn't provide primary_key_columns, fall back to whatever the
                # source detected during schema discovery. Otherwise we rely on sync-time
                # re-detection, which can disagree with discovery (e.g. permissions differences
                # across query paths) and leave incremental syncs without a primary key.
                effective_primary_key_columns = primary_key_columns or (
                    source_schema.detected_primary_keys if source_schema else None
                )
                # Lookback only applies to incremental (merge-by-PK makes the overlap re-read idempotent).
                # Mirror the schema-update path's IntegerField(min_value=0, max_value=5_184_000) so both
                # creation paths reject the same inputs instead of silently dropping null/float values.
                lookback_seconds = schema.get("incremental_field_lookback_seconds")
                # When the caller didn't set a lookback, fall back to the source-defined default
                # (e.g. Google Ads stats tables, whose recent rows Google keeps revising for days).
                # This loop is the single creation choke point, so the default reaches both the
                # wizard and one-shot flows; it's then validated by the bounds check just below.
                if lookback_seconds is None and source_schema is not None:
                    lookback_seconds = source_schema.default_incremental_lookback_seconds
                if lookback_seconds is not None:
                    # Coerce whole-number floats (e.g. 90.0) the way DRF's IntegerField does.
                    if isinstance(lookback_seconds, float) and lookback_seconds.is_integer():
                        lookback_seconds = int(lookback_seconds)
                    # bool is an int subclass — exclude it so true/false aren't treated as 1/0.
                    is_valid_int = isinstance(lookback_seconds, int) and not isinstance(lookback_seconds, bool)
                    if not is_valid_int or not (0 <= lookback_seconds <= 5_184_000):
                        new_source_model.delete()
                        return Response(
                            status=status.HTTP_400_BAD_REQUEST,
                            data={
                                "message": f"incremental_field_lookback_seconds must be an integer between 0 and 5184000 (60 days) for schema '{schema_name}'."
                            },
                        )
                sync_type_config = {
                    "incremental_field": incremental_field,
                    "incremental_field_type": incremental_field_type,
                    "schema_metadata": schema_metadata,
                    **({"primary_key_columns": effective_primary_key_columns} if effective_primary_key_columns else {}),
                    **(
                        {"incremental_field_lookback_seconds": lookback_seconds}
                        if sync_type == "incremental" and lookback_seconds is not None
                        else {}
                    ),
                }
            elif is_cdc_schema and not cdc_not_set_up:
                cdc_table_mode = schema.get("cdc_table_mode", "consolidated")
                sync_type_config = {
                    "cdc_mode": "snapshot",
                    "primary_key_columns": pk_columns_by_table.get(schema_name, []),
                    "schema_metadata": schema_metadata,
                    "cdc_table_mode": cdc_table_mode,
                }
            else:
                sync_type_config = {"schema_metadata": schema_metadata}

            # CDC schemas benefit from a tighter poll cadence — the extraction workflow is cheap
            # and the value prop is near-real-time. Other sync types use the 6h default.
            schema_sync_frequency_interval = (
                timedelta(minutes=5)
                if is_cdc_schema and not cdc_not_set_up and new_source_model.supports_scheduled_sync
                else timedelta(hours=6)
            )
            schema_model = ExternalDataSchema.objects.create(
                name=schema_name,
                team=self.team,
                source=new_source_model,
                should_sync=should_sync,
                sync_type=(None if cdc_not_set_up else sync_type) if new_source_model.supports_scheduled_sync else None,
                sync_time_of_day=sync_time_of_day if new_source_model.supports_scheduled_sync else None,
                sync_type_config=sync_type_config,
                description=source_schema.description if source_schema else None,
                label=schema_label_by_name.get(schema_name),
                sync_frequency_interval=schema_sync_frequency_interval,
                enabled_columns=enabled_columns,
                # Masking never applies to direct-query sources (they query live, nothing syncs);
                # the runtime engine additionally drops PK/incremental names defensively.
                masked_columns=None if is_direct_query else masked_columns,
                row_filters=row_filters,
            )

            # The CDC path is Postgres-only, and the direct paths are engine-specific —
            # `get_postgres_source_table_location` / `get_mysql_source_table_location` guarantee
            # non-None schema/table in their branches above. `cast` narrows for mypy without a
            # runtime check. The adapter no-ops for self-managed / no-publication.
            if is_cdc_schema and should_sync and cdc_enabled and cdc_adapter is not None:
                cdc_adapter.add_table(
                    new_source_model,
                    cast(str, metadata_source_schema),
                    cast(str, metadata_source_table_name),
                )

            if new_source_model.is_direct_postgres and should_sync:
                # Apply the picker's column subset on the very first DataWarehouseTable build,
                # not just on subsequent updates — otherwise users see all columns in HogQL until
                # they hit save again or a refresh runs.
                schema_model.table = upsert_direct_postgres_table(
                    None,
                    schema_name=schema_name,
                    source=new_source_model,
                    columns=filter_dwh_columns_by_enabled_columns(
                        postgres_columns_to_dwh_columns(source_schema.columns if source_schema else []),
                        enabled_columns,
                        source_schema.detected_primary_keys if source_schema else None,
                        incremental_field,
                        # Direct-postgres columns are keyed by raw, case-sensitive source names.
                        normalize=False,
                    ),
                    source_catalog=metadata_source_catalog,
                    source_schema=cast(str, metadata_source_schema),
                    source_table_name=cast(str, metadata_source_table_name),
                )
                schema_model.save(update_fields=["table"])
            elif new_source_model.is_direct_mysql and should_sync:
                schema_model.table = upsert_direct_mysql_table(
                    None,
                    schema_name=schema_name,
                    source=new_source_model,
                    columns=filter_dwh_columns_by_enabled_columns(
                        mysql_columns_to_dwh_columns(source_schema.columns if source_schema else []),
                        enabled_columns,
                        source_schema.detected_primary_keys if source_schema else None,
                        incremental_field,
                        # Direct-mysql columns are keyed by raw, case-sensitive source names.
                        normalize=False,
                    ),
                    source_schema=cast(str, metadata_source_schema),
                    source_table_name=cast(str, metadata_source_table_name),
                )
                schema_model.save(update_fields=["table"])
            elif new_source_model.is_direct_snowflake and should_sync:
                schema_model.table = upsert_direct_snowflake_table(
                    None,
                    schema_name=schema_name,
                    source=new_source_model,
                    columns=filter_dwh_columns_by_enabled_columns(
                        snowflake_columns_to_dwh_columns(source_schema.columns if source_schema else []),
                        enabled_columns,
                        source_schema.detected_primary_keys if source_schema else None,
                        incremental_field,
                        # Direct-snowflake columns are keyed by raw, case-sensitive source names.
                        normalize=False,
                    ),
                    source_catalog=metadata_source_catalog,
                    source_schema=cast(str, metadata_source_schema),
                    source_table_name=cast(str, metadata_source_table_name),
                )
                schema_model.save(update_fields=["table"])

            if should_sync and new_source_model.supports_scheduled_sync:
                active_schemas.append(schema_model)

        # Create all sync schedules over a single shared Temporal connection. Creating them
        # one call at a time reconnects to Temporal on every iteration, which does not scale
        # to sources with thousands of schemas (e.g. a Slack workspace with thousands of
        # channels).
        try:
            schedule_errors = bulk_create_external_data_job_schedules(
                [(active_schema, active_schema.should_sync) for active_schema in active_schemas]
            )
            for schema_id, schedule_error in schedule_errors:
                # The source model was already created, so a partial schedule failure
                # shouldn't fail the request — log each failure and carry on.
                logger.exception(
                    "Could not trigger external data job",
                    exc_info=schedule_error,
                    schema_id=schema_id,
                )
        except Exception as e:
            logger.exception("Could not trigger external data job", exc_info=e)

        # Per-source schema discovery schedule. Runs every 6h so newly added
        # upstream resources (Slack channels, Postgres tables, …) get picked up
        # without re-discovering on every per-schema sync tick. Direct-query
        # sources resolve schemas at query time, so they opt out of all
        # background sync — including this discovery cadence.
        if new_source_model.supports_scheduled_sync:
            try:
                sync_discover_schemas_schedule(new_source_model, create=True)
            except Exception as e:
                logger.exception("Could not create schema discovery schedule", exc_info=e)

        # Start CDC extraction schedule if any CDC schemas are active
        if cdc_enabled:
            try:
                sync_cdc_extraction_schedule(new_source_model, create=True)
                ensure_cdc_slot_cleanup_schedule()
            except Exception as e:
                logger.exception("Could not create CDC schedules", exc_info=e)

        if new_source_model.revenue_analytics_config_safe.enabled:
            managed_viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
                team=self.team,
                kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
            )
            managed_viewset.sync_views()
            ensure_person_join(self.team.pk, new_source_model.prefix)

        # `source` (web/api/mcp) is derived from the request by report_user_action; `created_via`
        # is the caller's explicit intent. They usually agree but are kept separate so a transport
        # change (e.g. a new wrapper UA) doesn't silently rewrite historical attribution.
        report_user_action(
            cast(User, request.user),
            "data warehouse source created",
            {
                "source_type": source_type,
                "created_via": created_via,
                "source_access_method": access_method,
                "direct_query_enabled": direct_query_enabled,
                "schema_count": len(active_schemas),
                "source_id": str(new_source_model.pk),
            },
            team=self.team,
            request=request,
        )

        return Response(status=status.HTTP_201_CREATED, data={"id": new_source_model.pk})

    def _setup_cdc_resources(
        self, adapter: CDCSourceAdapter, source_model: ExternalDataSource, payload: dict
    ) -> str | None:
        """Provision CDC for an existing source by delegating to the engine adapter.

        Writes universal CDC fields (mode, lag thresholds, auto-drop policy) plus the
        adapter-supplied resource fields (slot/publication identifiers, consistent
        point, …) into ``source_model.job_inputs`` and saves. Returns an error string
        on failure, or None on success. Callers decide whether to delete the source
        on failure (create flow does; enable_cdc does not).
        """
        management_mode = payload.get("cdc_management_mode", "posthog")
        logger.info(
            "Setting up CDC resources for source",
            source_id=str(source_model.pk),
            source_type=source_model.source_type,
            management_mode=management_mode,
        )

        resource_fields, error = adapter.setup_resources(source_model, payload)
        if error is not None:
            logger.warning(
                "CDC resource setup failed",
                source_id=str(source_model.pk),
                source_type=source_model.source_type,
                management_mode=management_mode,
                error=error,
            )
            return error

        logger.info(
            "CDC resources provisioned",
            source_id=str(source_model.pk),
            management_mode=management_mode,
            slot_name=resource_fields.get("cdc_slot_name"),
            publication_name=resource_fields.get("cdc_publication_name"),
            resource_keys=sorted(resource_fields.keys()),
        )

        job_inputs = dict(source_model.job_inputs or {})
        job_inputs.update(
            {
                "cdc_enabled": True,
                "cdc_auto_drop_slot": payload.get("cdc_auto_drop_slot", True),
                "cdc_lag_warning_threshold_mb": payload.get(
                    "cdc_lag_warning_threshold_mb", DEFAULT_LAG_WARNING_THRESHOLD_MB
                ),
                "cdc_lag_critical_threshold_mb": payload.get(
                    "cdc_lag_critical_threshold_mb", DEFAULT_LAG_CRITICAL_THRESHOLD_MB
                ),
            }
        )
        job_inputs.update(resource_fields)
        source_model.job_inputs = job_inputs
        source_model.save(update_fields=["job_inputs", "updated_at"])
        return None

    def prefix_required(self, source_type: str) -> bool:
        # A prefix is only needed when a no-prefix source of the same type already
        # exists. Two no-prefix sources would write to the same table names; sources
        # with distinct prefixes (including one no-prefix + N prefixed) have separate
        # table namespaces and cannot collide.
        no_prefix_source_exists = (
            ExternalDataSource.objects.exclude(deleted=True)
            .filter(team_id=self.team.pk, source_type=source_type)
            .filter(Q(prefix__isnull=True) | Q(prefix=""))
            .exists()
        )
        return no_prefix_source_exists

    def prefix_exists(self, source_type: str, prefix: str) -> bool:
        prefix_exists = (
            ExternalDataSource.objects.exclude(deleted=True)
            .filter(team_id=self.team.pk, source_type=source_type, prefix=prefix)
            .exists()
        )
        return prefix_exists

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()

        schemas = list(
            ExternalDataSchema.objects.exclude(deleted=True)
            .filter(team_id=self.team_id, source_id=instance.id)
            .select_related("table")
            .all()
        )

        # Soft-delete source, schemas, tables, and companion _cdc tables atomically
        # first so DB state is consistent even if the external cleanup below fails
        with transaction.atomic():
            for schema in schemas:
                if schema.table:
                    schema.table.soft_delete()

            # Bulk soft-delete the schema rows in a single UPDATE. Per-row soft_delete()
            # runs a SELECT + UPDATE + activity-log write each, which does not scale to
            # sources with thousands of schemas (e.g. a Slack workspace with thousands of
            # channels).
            deleted_at = datetime.now(UTC)
            ExternalDataSchema.objects.filter(team_id=self.team_id, id__in=[schema.id for schema in schemas]).update(
                deleted=True, deleted_at=deleted_at
            )
            # Mirror the bulk update onto the in-memory objects so the post-atomic
            # `schema.delete_table()` save() below doesn't overwrite deleted=True with the
            # stale in-memory value.
            for schema in schemas:
                schema.deleted = True
                schema.deleted_at = deleted_at

            # Clean up CDC companion tables (e.g. {name}_cdc) — these are standalone
            # DataWarehouseTable records linked to the source but not to schema.table.
            DataWarehouseTable.objects.filter(
                external_data_source_id=instance.id,
                team_id=self.team_id,
                deleted=False,
            ).exclude(id__in=[s.table_id for s in schemas if s.table_id is not None]).update(deleted=True)

            instance.soft_delete()

        # Best-effort webhook cleanup — soft-deletes are already committed
        source_type = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type)
        if isinstance(source, WebhookSource) and instance.job_inputs:
            try:
                config = source.parse_config(instance.job_inputs)
                delete_webhook_and_hog_function(
                    team=self.team,
                    source=source,
                    config=config,
                    source_id=str(instance.pk),
                )
            except Exception as e:
                capture_exception(e)

        # Best-effort external cleanup — soft-deletes are already committed
        latest_running_job = (
            ExternalDataJob.objects.filter(pipeline_id=instance.pk, team_id=instance.team_id)
            .order_by("-created_at")
            .first()
        )
        if latest_running_job and latest_running_job.workflow_id and latest_running_job.status == "Running":
            cancel_external_data_workflow(latest_running_job.workflow_id)

        # Delete all schema sync schedules over a single shared Temporal connection — see
        # the matching comment in `create`. Guarded so a Temporal-connect failure here
        # doesn't skip the source/discovery schedule and S3 cleanup below.
        try:
            schedule_delete_errors = bulk_delete_external_data_schedules([str(schema.id) for schema in schemas])
            for schema_id, schedule_delete_error in schedule_delete_errors:
                capture_exception(schedule_delete_error, {"schema_id": schema_id})
        except Exception as e:
            capture_exception(e)

        for schema in schemas:
            try:
                schema.delete_table()
            except Exception as e:
                capture_exception(e)

        try:
            delete_external_data_schedule(str(instance.id))
        except Exception as e:
            capture_exception(e)

        try:
            delete_discover_schemas_schedule(str(instance.id))
        except Exception as e:
            capture_exception(e)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["POST"], detail=True)
    def reload(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSource = self.get_object()

        if instance.is_direct_query:
            return self.refresh_schemas(request, *args, **kwargs)

        if is_any_external_data_schema_paused(self.team_id):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please increase your billing limit to resume syncing."},
            )

        try:
            trigger_external_data_source_workflow(instance)

        except temporalio.service.RPCError:
            # if the source schedule has been removed - trigger the schema schedules
            instance.reload_schemas()

        except Exception as e:
            logger.exception("Could not trigger external data job", exc_info=e)
            raise

        instance.status = "Running"
        instance.save()
        return Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    @extend_schema(
        responses={
            200: {
                "type": "object",
                "properties": {
                    "added": {"type": "integer"},
                    "deleted": {"type": "integer"},
                    "total_tables_seen": {"type": "integer"},
                },
            }
        }
    )
    def refresh_schemas(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Fetch current schema/table list from the source and create any new ExternalDataSchema rows (no data sync)."""
        instance: ExternalDataSource = self.get_object()
        logger.debug(
            "refresh_schemas called",
            source_id=str(instance.id),
            team_id=self.team_id,
            source_type=instance.source_type,
        )
        if not instance.job_inputs:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Source has no configuration."},
            )
        source: AnySource | None = None
        try:
            source_type = ExternalDataSourceType(instance.source_type)
            source = SourceRegistry.get_source(source_type)
            config = source.parse_config(instance.job_inputs)
            # Explicit user action — bypass any cached schema discovery so newly added
            # upstream resources (e.g. Slack channels) appear immediately.
            schemas = source.get_schemas(config, self.team_id, force_refresh=True)
            connection_metadata = (
                get_direct_connection_metadata(
                    source_impl=source,
                    source_config=config,
                    team_id=self.team_id,
                    source_model=instance,
                    fallback=instance.connection_metadata,
                )
                if instance.is_direct_query
                else instance.connection_metadata
            )
            schema_names = {s.name: s.label for s in schemas}
            logger.info(
                "refresh_schemas fetched from source",
                source_id=str(instance.id),
                schema_count=len(schema_names),
                schema_names=schema_names,
            )
        except Exception as e:
            error_message, is_expected_source_error = _classify_refresh_schemas_error(source, e)
            logger.exception(
                "Could not fetch schemas from source",
                exc_info=e,
                source_id=str(instance.id),
                team_id=self.team_id,
                source_type=instance.source_type,
                error_type=type(e).__name__,
                is_expected_source_error=is_expected_source_error,
            )
            if not is_expected_source_error:
                capture_exception(
                    e,
                    {
                        "source_id": str(instance.id),
                        "source_type": instance.source_type,
                        "team_id": self.team_id,
                        "refresh_schemas": True,
                    },
                )
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": error_message},
            )

        descriptions = {s.name: s.description for s in schemas}
        with transaction.atomic():
            ExternalDataSource._base_manager.filter(pk=instance.pk).select_for_update().get()
            if instance.is_direct_query and connection_metadata != instance.connection_metadata:
                instance.connection_metadata = connection_metadata
                instance.save(update_fields=["connection_metadata", "updated_at"])
            # Migrate/dedupe legacy rows before sync_old_schemas; non-Postgres only once namespace cleared.
            name_substitutions: dict[str, str] = {}
            if instance.source_type == ExternalDataSourceType.POSTGRES:
                name_substitutions = reconcile_postgres_refresh_name_substitutions(
                    source=instance,
                    source_schemas=schemas,
                    team_id=self.team_id,
                )
            elif source_namespace_is_blank(instance) and is_multi_schema_capable_sql_source(instance.source_type):
                name_substitutions = apply_sql_warehouse_refresh_migration(source=instance, team_id=self.team_id)

            if name_substitutions:
                schema_names = {name_substitutions.get(name, name): label for name, label in schema_names.items()}
                descriptions = {
                    name_substitutions.get(name, name): description for name, description in descriptions.items()
                }
            schemas_created, schemas_deleted = sync_old_schemas_with_new_schemas(
                schema_names,
                source_id=str(instance.id),
                team_id=self.team_id,
                descriptions=descriptions,
            )

            if instance.source_type == ExternalDataSourceType.POSTGRES:
                reconciled_deleted_schemas = reconcile_postgres_schemas(
                    source=instance,
                    source_schemas=schemas,
                    team_id=self.team_id,
                )
                if reconciled_deleted_schemas:
                    schemas_deleted = list({*schemas_deleted, *reconciled_deleted_schemas})
            elif instance.source_type == ExternalDataSourceType.MYSQL:
                reconciled_deleted_schemas = reconcile_mysql_schemas(
                    source=instance,
                    source_schemas=schemas,
                    team_id=self.team_id,
                )
                if reconciled_deleted_schemas:
                    schemas_deleted = list({*schemas_deleted, *reconciled_deleted_schemas})
            elif instance.source_type == ExternalDataSourceType.SNOWFLAKE:
                reconciled_deleted_schemas = reconcile_snowflake_schemas(
                    source=instance,
                    source_schemas=schemas,
                    team_id=self.team_id,
                )
                if reconciled_deleted_schemas:
                    schemas_deleted = list({*schemas_deleted, *reconciled_deleted_schemas})
            elif isinstance(source, (SQLSource, ClickHouseSource)) and source.supports_column_selection:
                # ClickHouse isn't a SQLSource but exposes the same column-selection
                # capability and reconcile hook, so it reuses this path.
                source.reconcile_schema_metadata(source=instance, source_schemas=schemas, team_id=self.team_id)
        logger.debug(
            "refresh_schemas completed",
            source_id=str(instance.id),
            team_id=self.team_id,
            added=len(schemas_created),
            deleted=len(schemas_deleted),
            total_tables_seen=len(schemas),
        )
        return Response(
            status=status.HTTP_200_OK,
            data={
                "added": len(schemas_created),
                "deleted": len(schemas_deleted),
                "total_tables_seen": len(schemas),
            },
        )

    @extend_schema(request=DatabaseSchemaRequestSerializer)
    @action(methods=["POST"], detail=False)
    def database_schema(self, request: Request, *arg: Any, **kwargs: Any):
        source_type = request.data.get("source_type", None)

        if source_type is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Missing required parameter: source_type"},
            )

        secret_ref_response = _unresolved_secret_ref_response(request.data)
        if secret_ref_response is not None:
            return secret_ref_response

        try:
            source_type_model = ExternalDataSourceType(source_type)
        except ValueError:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Unknown source_type '{source_type}'"},
            )
        source = SourceRegistry.get_source(source_type_model)
        is_valid, errors = source.validate_config(request.data)
        if not is_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid source config: {', '.join(errors)}"},
            )
        source_config: Config = source.parse_config(request.data)

        access_method = request.data.get("access_method", ExternalDataSource.AccessMethod.WAREHOUSE)
        if isinstance(source, (PostgresSource, MySQLSource)):
            credentials_valid, credentials_error = source.validate_credentials_for_access_method(
                cast(Any, source_config), self.team_id, access_method
            )
        elif isinstance(source, CustomSource):
            # Schema discovery for an as-yet-uncreated source: an integration-backed manifest may only use
            # an unbound integration owned by the requester, or the probe could send another source's token
            # to the submitted host.
            credentials_valid, credentials_error = source.validate_credentials(
                source_config, self.team_id, owner_user_id=self.request.user.id
            )
        else:
            credentials_valid, credentials_error = source.validate_credentials(source_config, self.team_id)
        if not credentials_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": credentials_error or "Invalid credentials"},
            )

        try:
            schemas = source.get_schemas(source_config, self.team_id)
        except NotImplementedError:
            # Source doesn't implement schema discovery (e.g. an unreleased source), so there are
            # no tables to list — a caller mistake, not a server error worth capturing. Mirrors `setup`.
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Source type '{source_type}' does not support schema discovery."},
            )
        except Exception as e:
            error_message, is_expected_source_error = _classify_refresh_schemas_error(source, e)
            if not is_expected_source_error:
                capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": error_message},
            )

        # Best-effort per-endpoint scope probe — transient failure falls back to "available".
        try:
            endpoint_permissions = source.get_endpoint_permissions(
                source_config, self.team_id, [schema.name for schema in schemas]
            )
        except Exception as e:
            capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
            endpoint_permissions = {schema.name: None for schema in schemas}

        # Cache the CDC flag once: in non-DEBUG environments this calls posthoganalytics.feature_enabled,
        # which makes a network round-trip per call. With large schema lists (e.g. Slack workspaces with
        # thousands of channels) the per-iteration call inflated the response loop past the 120s gateway.
        cdc_enabled = is_cdc_enabled_for_team(self.team)
        xmin_enabled = is_xmin_enabled_for_team(self.team)
        # xmin is Postgres-only — gate on the source type so the capability never leaks to another SQL source.
        is_postgres = source_type_model == ExternalDataSourceType.POSTGRES
        data = [
            {
                "table": schema.name,
                "label": schema.label,
                "should_sync": False,
                "incremental_fields": schema.incremental_fields,
                "incremental_available": schema.supports_incremental,
                "append_available": schema.supports_append,
                "cdc_available": schema.supports_cdc if cdc_enabled else None,
                "xmin_available": schema.supports_xmin if (is_postgres and xmin_enabled) else None,
                "incremental_field": schema.incremental_fields[0]["field"]
                if len(schema.incremental_fields) > 0 and len(schema.incremental_fields[0]["field"]) > 0
                else None,
                "sync_type": None,
                "rows": schema.row_count,
                "supports_webhooks": schema.supports_webhooks,
                "webhook_only": schema.webhook_only,
                "description": schema.description,
                "should_sync_default": schema.should_sync_default,
                "available_columns": [
                    {"field": col_name, "label": col_name, "type": col_type, "nullable": nullable}
                    for col_name, col_type, nullable in schema.columns
                ],
                "detected_primary_keys": schema.detected_primary_keys,
                "permission_error": endpoint_permissions.get(schema.name),
                "rls_warning": schema.rls_warning,
            }
            for schema in schemas
        ]
        return Response(status=status.HTTP_200_OK, data=data)

    @extend_schema(request=SourceSetupSerializer, responses={201: SourceSetupResponseSerializer})
    @action(methods=["POST"], detail=False)
    def setup(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """One-shot data warehouse source setup.

        Validate credentials, discover available tables, enable them all with sensible sync defaults
        (incremental where supported, else append, else full refresh), and create the source in a single
        call — the caller never has to assemble a `schemas` array. For sources that support webhooks
        (e.g. Stripe), a webhook is auto-registered after creation: on success webhook-capable tables
        switch to real-time webhook sync (unlocking webhook-only tables); on failure the polling
        defaults stay in place. For fine-grained table/sync control, use the lower-level
        `database_schema` + `create` flow instead.
        """
        # No database context needed here (unlike the read serializer), and skipping it avoids building
        # the HogQL Database on this hot path.
        serializer = SourceSetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_type = serializer.validated_data["source_type"]
        payload = dict(serializer.validated_data.get("payload") or {})

        secret_ref_response = _unresolved_secret_ref_response(payload)
        if secret_ref_response is not None:
            return secret_ref_response

        credential: PendingSourceCredential | None = None
        credential_id = payload.pop("credential_id", None)
        if credential_id is not None:
            try:
                credential = PendingSourceCredential.objects.for_team(self.team_id).get(
                    id=credential_id, expires_at__gt=timezone.now()
                )
            except (PendingSourceCredential.DoesNotExist, ValueError, TypeError, DjangoValidationError):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": f"Stored credential '{credential_id}' not found or expired"},
                )
            if credential.source_type != source_type:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": f"Stored credential '{credential_id}' is for "
                        f"'{credential.source_type}', not '{source_type}'"
                    },
                )
            # Stored credentials win over inline keys so an agent can't override what the user entered.
            payload = {**payload, **credential.payload}

        source_type_model = ExternalDataSourceType(source_type)
        source = SourceRegistry.get_source(source_type_model)

        error_response, source_config = self._validate_source_config_and_credentials(source, source_type_model, payload)
        if error_response is not None or source_config is None:
            return error_response or Response(status=status.HTTP_400_BAD_REQUEST)

        if isinstance(source, CustomSource):
            # Validation may have adopted static OAuth2 secrets into an integration row and rewritten
            # the config to point at it. `_create_external_data_source` below re-parses the raw payload
            # (it skips the credential gate), so propagate the rewrite onto the payload — the created
            # source must store the row pointer, never the raw secrets.
            validated_payload = source_config.to_dict()
            for key in ("auth_oauth2_integration_id", "auth_oauth2_client_secret", "auth_oauth2_refresh_token"):
                if validated_payload.get(key):
                    payload[key] = validated_payload[key]
                else:
                    payload.pop(key, None)

        try:
            source_schemas = source.get_schemas(source_config, self.team_id)
        except NotImplementedError:
            # Source doesn't implement schema discovery (e.g. an unreleased source) so it can't be
            # set up via this one-shot flow — a caller mistake, not a server error worth capturing.
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Source type '{source_type}' does not support one-shot setup."},
            )
        except Exception as e:
            capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": str(e)})

        if not source_schemas:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "No tables found for this source. Check the credentials and permissions."},
            )

        # Build the schemas array server-side so the caller never has to. We've already validated
        # config + credentials above, so `_create_external_data_source` skips that second gate
        # (`skip_credential_validation`) to avoid a duplicate live credential round-trip.
        payload["schemas"] = build_default_schemas(source_schemas)

        response = self._create_external_data_source(
            request,
            source_type=source_type,
            payload=payload,
            prefix=serializer.validated_data.get("prefix"),
            description=serializer.validated_data.get("description"),
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            created_via=ExternalDataSource.CreatedVia.MCP,
            direct_query_enabled=serializer.validated_data.get("direct_query_enabled", True),
            skip_credential_validation=True,
        )
        # Stored credentials are single-use: once the source owns them (in job_inputs), drop the stash.
        if credential is not None and response.status_code == status.HTTP_201_CREATED:
            credential.delete()

        if response.status_code == status.HTTP_201_CREATED and isinstance(source, WebhookSource):
            webhook_result = self._auto_register_webhook(
                source, source_config, str(response.data["id"]), source_schemas
            )
            if webhook_result is not None:
                response.data["webhook"] = webhook_result
        return response

    @extend_schema(request=SourcePreviewRequestSerializer, responses={200: SourcePreviewResponseSerializer})
    @action(methods=["POST"], detail=False)
    def preview_resource(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Read a bounded sample of rows for one resource of a Custom REST source.

        Lets a manifest author verify `data_selector`, `primary_key`, and the incremental
        `cursor_path` against live data before creating the source. Only `source_type: "Custom"`
        is supported — other source types return 400. The read is bounded (single page per
        resource, capped row count, short timeouts, no redirects). Manifest, validation, and SSRF
        problems return 400; a live fetch failure returns 200 with `error` set and empty `rows`.
        """
        serializer = SourcePreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_type = serializer.validated_data["source_type"]
        source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
        if not isinstance(source, CustomSource):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Preview is not supported for source type '{source_type}'."},
            )

        payload = dict(serializer.validated_data.get("payload") or {})
        is_valid, errors = source.validate_config(payload)
        if not is_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid source config: {', '.join(errors)}"},
            )
        source_config = source.parse_config(payload)

        try:
            # preview_resource runs its own SSRF host check and bounded live read, so no
            # separate validate_credentials probe — the read is the credential check.
            result = source.preview_resource(
                cast(CustomSourceConfig, source_config),
                self.team_id,
                serializer.validated_data["resource_name"],
                serializer.validated_data["limit"],
                owner_user_id=self.request.user.id,
            )
        except ValueError as e:
            # ManifestValidationError (a ValueError) for manifest/graph/URL issues, or a plain
            # ValueError for an unknown resource_name / dependency cycle — all caller mistakes.
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": str(e)})

        return Response(
            status=status.HTTP_200_OK,
            data={
                "rows": result.rows,
                "row_count": result.row_count,
                "columns": result.columns,
                "error": result.error,
            },
        )

    @extend_schema(
        request=DraftCustomManifestRequestSerializer,
        responses={200: DraftCustomManifestResponseSerializer},
    )
    @action(methods=["POST"], detail=False)
    def draft_custom_manifest(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Draft a Custom REST source manifest from API documentation using an LLM.

        Reads the docs (a URL fetched server-side, or pasted text / OpenAPI spec), asks the model to
        author a RESTAPIConfig manifest, and validates it against the create-path checks — repairing
        against validation errors up to a small budget. Returns the manifest for the user to review
        and tweak in the builder before creating the source; it does NOT create anything. Gated by the
        `dwh-custom-source-ai-builder` flag, and requires the org to have approved AI data processing,
        since the docs are sent to the LLM gateway.
        """
        # Gate on access (flag) then consent before validating input shape, so a caller without the
        # rollout or AI-data-processing opt-in is turned away before learning the request schema.
        if not is_custom_source_ai_builder_enabled_for_team(self.team):
            return Response(
                status=status.HTTP_404_NOT_FOUND,
                data={"message": "AI manifest drafting is not enabled for this organization."},
            )

        if self.team.organization.is_ai_data_processing_approved is not True:
            return Response(
                status=status.HTTP_403_FORBIDDEN,
                data={"message": "Enable AI data processing for this organization to use AI manifest drafting."},
            )

        serializer = DraftCustomManifestRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        docs_text = (data.get("docs_text") or "").strip()
        docs_source = "pasted_text" if docs_text else "fetched_url"
        if not docs_text:
            try:
                docs_text = fetch_docs_text(data["docs_url"])
            except DocsFetchError as e:
                return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": str(e)})

        try:
            result = draft_manifest_sync(
                team_id=self.team_id,
                source_name=data.get("source_name") or "",
                docs_text=docs_text,
            )
        except APIConnectionError as e:
            capture_exception(e, {"team_id": self.team_id})
            return Response(
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                data={
                    "message": "Couldn't reach the AI service. If you're running locally, the LLM gateway isn't running — author the manifest manually instead."
                },
            )
        except Exception as e:
            capture_exception(e, {"team_id": self.team_id})
            return Response(
                status=status.HTTP_502_BAD_GATEWAY,
                data={"message": "The manifest drafting service failed. Try again, or author the manifest manually."},
            )

        # Success-path telemetry: this is a paid, unbilled-to-customer Opus path, so capture how it
        # performed (status, repair rounds, tables, where the docs came from) to drive a funnel from
        # draft → source created. No docs content or credentials — none are accepted here anymore.
        report_user_action(
            cast(User, request.user),
            "data warehouse custom source manifest drafted",
            {
                "draft_status": result.status,
                "attempts": result.attempts,
                "table_count": len(result.resource_names),
                "docs_source": docs_source,
            },
            team=self.team,
            request=request,
        )

        return Response(
            status=status.HTTP_200_OK,
            data={
                "draft_status": result.status,
                "manifest_json": result.manifest_json,
                "resource_names": result.resource_names,
                "attempts": result.attempts,
                "error": result.error,
            },
        )

    def _auto_register_webhook(
        self,
        source: WebhookSource,
        source_config: Config,
        source_id: str,
        source_schemas: list[SourceSchema],
    ) -> dict | None:
        """Best-effort webhook auto-registration for one-shot setup.

        The source was just created with polling sync defaults (webhook-only tables disabled). If the
        source supports webhook auto-creation and the credentials allow it, register the webhook and
        switch every webhook-capable table to the webhook sync method — unlocking webhook-only tables.
        Failure never breaks setup: the polling defaults stay in place and webhook-only tables remain
        disabled, exactly as if the source didn't support webhooks.
        """
        webhook_capable = {s.name for s in source_schemas if s.supports_webhooks}
        if not webhook_capable or source.webhook_template is None:
            return None

        instance = ExternalDataSource.objects.get(pk=source_id, team_id=self.team_id)
        eligible_schemas = list(
            ExternalDataSchema.objects.filter(source=instance, team_id=self.team_id, name__in=webhook_capable).exclude(
                deleted=True
            )
        )
        if not eligible_schemas:
            return None

        def failure(error: str | None) -> dict:
            return {"success": False, "webhook_url": None, "error": error, "pending_inputs": []}

        try:
            hog_fn_result = get_or_create_webhook_hog_function(
                team=self.team,
                source=source,
                source_id=str(instance.pk),
                eligible_schemas=eligible_schemas,
            )
            if hog_fn_result.error or hog_fn_result.hog_function is None:
                return failure(hog_fn_result.error)

            registration = create_and_register_webhook(source, source_config, hog_fn_result, self.team_id)
        except Exception as e:
            capture_exception(e, {"source_id": source_id, "team_id": self.team_id})
            return failure(str(e))

        if not registration.success:
            # The external registration failed (e.g. credentials can't create webhooks), so the
            # handler would never receive events — remove it and keep the polling defaults.
            hog_function = hog_fn_result.hog_function
            hog_function.deleted = True
            hog_function.enabled = False
            hog_function.save(update_fields=["deleted", "enabled"])
            return failure(registration.error)

        for schema in eligible_schemas:
            newly_enabled = not schema.should_sync
            schema.sync_type = ExternalDataSchema.SyncType.WEBHOOK
            schema.should_sync = True
            schema.save(update_fields=["sync_type", "should_sync"])
            if newly_enabled:
                # Webhook-only tables were created disabled, so no sync schedule exists yet. The
                # schedule still matters for webhook schemas: it ingests the buffered webhook events.
                try:
                    sync_external_data_job_workflow(schema, create=True)
                except Exception as e:
                    logger.exception(
                        "Could not create sync schedule for webhook schema", exc_info=e, schema_id=str(schema.id)
                    )

        return {
            "success": True,
            "webhook_url": registration.webhook_url,
            "error": None,
            "pending_inputs": list(registration.pending_inputs),
        }

    def _validate_source_config_and_credentials(
        self,
        source: AnySource,
        source_type_model: ExternalDataSourceType,
        payload: dict,
        access_method: str = ExternalDataSource.AccessMethod.WAREHOUSE,
    ) -> tuple[Response | None, Config | None]:
        """Run the config + live credential gate (including the SSRF host check) for a source payload."""
        if isinstance(source, CustomSource):
            # The OAuth2 integration row pointer is server-managed: validation derives it by adopting
            # the submitted auth_oauth2_* secrets into a row. Never trust a client-supplied pointer on
            # a pre-create seam — it could reference a row the caller shouldn't consume.
            payload.pop("auth_oauth2_integration_id", None)
        is_valid, errors = source.validate_config(payload)
        if not is_valid:
            return (
                Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": f"Invalid source config: {', '.join(errors)}"},
                ),
                None,
            )
        source_config: Config = source.parse_config(payload)

        if isinstance(source, (PostgresSource, MySQLSource)):
            credentials_valid, credentials_error = source.validate_credentials_for_access_method(
                cast(Any, source_config), self.team_id, access_method
            )
        elif isinstance(source, CustomSource):
            # Create-time validation for an integration-backed manifest may only use an unbound integration
            # owned by the requester, so the probe can't send another source's token to the submitted host.
            credentials_valid, credentials_error = source.validate_credentials(
                source_config, self.team_id, owner_user_id=self.request.user.id
            )
        else:
            credentials_valid, credentials_error = source.validate_credentials(source_config, self.team_id)
        if not credentials_valid:
            return (
                Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": credentials_error or "Invalid credentials"},
                ),
                None,
            )
        return None, source_config

    @extend_schema(request=SourceCredentialCreateSerializer, responses={201: SourceCredentialSerializer})
    @action(methods=["POST"], detail=False)
    def store_credentials(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Validate and store credentials for a data warehouse source without creating the source.

        Backs the source connect page: the user enters credentials directly in PostHog, they are
        checked against a live connection, then stashed encrypted in a temporary store. The returned
        credential id can be passed to `setup` as {'credential_id': <id>} to create the source — so
        secrets never travel through an agent conversation. The stash is single-use: it is deleted
        as soon as `setup` consumes it, and expires after 24 hours if never consumed.
        """
        serializer = SourceCredentialCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_type = serializer.validated_data["source_type"]
        payload = dict(serializer.validated_data["payload"])

        for key, value in payload.items():
            if isinstance(value, str):
                payload[key] = value.strip()

        source_type_model = ExternalDataSourceType(source_type)
        source = SourceRegistry.get_source(source_type_model)

        error_response, _ = self._validate_source_config_and_credentials(source, source_type_model, payload)
        if error_response is not None:
            return error_response

        # Opportunistically purge expired stashes — there is no separate cleanup job.
        PendingSourceCredential.objects.for_team(self.team_id).filter(expires_at__lte=timezone.now()).delete()

        credential = PendingSourceCredential.objects.create(
            team_id=self.team_id,
            source_type=source_type,
            payload=payload,
            created_by=cast(User, request.user),
        )

        return Response(
            status=status.HTTP_201_CREATED,
            data=SourceCredentialSerializer(
                {
                    "credential_id": credential.id,
                    "source_type": source_type,
                    "created_at": credential.created_at,
                    "expires_at": credential.expires_at,
                }
            ).data,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="source_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only return stored credentials for this source type (e.g. 'Stripe', 'Postgres').",
            )
        ],
        responses=SourceCredentialSerializer(many=True),
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def stored_credentials(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List credentials stored via the source connect page that haven't been consumed yet.

        Returns metadata only (id, source type, timestamps) — never the secrets themselves. Stored
        credentials are temporary: they disappear once consumed by `setup` or when they expire.
        Newest first, so after a user confirms they've finished the connect page, the first entry
        for the source type is the one to pass to `setup`.
        """
        queryset = (
            PendingSourceCredential.objects.for_team(self.team_id)
            .filter(expires_at__gt=timezone.now())
            .order_by("-created_at")
        )
        source_type = request.query_params.get("source_type")
        if source_type:
            queryset = queryset.filter(source_type=source_type)

        data = [
            {
                "credential_id": credential.id,
                "source_type": credential.source_type,
                "created_at": credential.created_at,
                "expires_at": credential.expires_at,
            }
            for credential in queryset
        ]
        return Response(status=status.HTTP_200_OK, data=SourceCredentialSerializer(data, many=True).data)

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {
                        "valid": {"type": "boolean"},
                        "errors": {"type": "array", "items": {"type": "string"}},
                    },
                },
                description="Whether the Postgres database satisfies CDC prerequisites.",
            ),
            400: OpenApiResponse(description="Invalid config, disallowed host, or connection failure."),
        },
    )
    @action(methods=["POST"], detail=False)
    def check_cdc_prerequisites(self, request: Request, *arg: Any, **kwargs: Any):
        """Validate CDC prerequisites against a live Postgres connection.

        Used by the source wizard to surface ✅/❌ checks before source creation,
        and by the self-managed setup popup to verify user-created publications.
        """
        source_type = request.data.get("source_type")
        if not source_type_supports_cdc(source_type):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "CDC prerequisite checks are only supported for CDC enabled sources."},
            )

        source_impl: PostgresSource = PostgresSource()
        is_valid, errors = source_impl.validate_config(request.data)
        if not is_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid source config: {', '.join(errors)}"},
            )
        config = source_impl.parse_config(request.data)

        # SSRF protection: reject internal/private hosts (same as validate_credentials).
        is_ssh_valid, ssh_errors = source_impl.ssh_tunnel_is_valid(config, self.team_id)
        if not is_ssh_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": ssh_errors or "SSH tunnel host not allowed"},
            )
        valid_host, host_errors = source_impl.is_database_host_valid(
            config.host,
            self.team_id,
            using_ssh_tunnel=config.ssh_tunnel.enabled if config.ssh_tunnel else False,
        )
        if not valid_host:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": host_errors or "Host not allowed"},
            )

        management_mode = request.data.get("cdc_management_mode", "posthog")
        if management_mode not in ("posthog", "self_managed"):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "cdc_management_mode must be 'posthog' or 'self_managed'."},
            )

        tables = request.data.get("tables") or []
        slot_name = request.data.get("cdc_slot_name") or None
        publication_name = request.data.get("cdc_publication_name") or None

        try:
            prereq_errors = source_impl.check_cdc_prerequisites(
                config,
                management_mode=management_mode,
                tables=tables,
                slot_name=slot_name,
                publication_name=publication_name,
            )
        except (OperationalError, BaseSSHTunnelForwarderError, SSLRequiredError) as e:
            # Probing a user-supplied database to validate it is expected to fail when the host,
            # credentials, or SSH tunnel are wrong or the server drops the connection. Surface it
            # to the wizard as a 400, but don't capture it — these are user/upstream connection
            # problems, not bugs in our code, and capturing every one floods error tracking.
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to Postgres to check prerequisites: {e}"},
            )
        except Exception as e:
            capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to Postgres to check prerequisites: {e}"},
            )

        return Response(
            status=status.HTTP_200_OK,
            data={"valid": len(prereq_errors) == 0, "errors": prereq_errors},
        )

    def _get_cdc_adapter_or_400(self, instance: ExternalDataSource) -> tuple[CDCSourceAdapter | None, Response | None]:
        """Look up the engine adapter for an existing source. Returns 400 if the
        source's type doesn't support CDC."""
        try:
            return get_cdc_adapter(instance), None
        except ValueError:
            return None, Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"CDC is not supported for source type: {instance.source_type}"},
            )

    @action(methods=["POST"], detail=True)
    def check_cdc_prerequisites_for_source(self, request: Request, *arg: Any, **kwargs: Any):
        """Validate CDC prerequisites for an existing source using its stored credentials.

        The detail=False ``check_cdc_prerequisites`` action is for the creation wizard,
        where the client still holds the raw connection config (incl. password) in the
        form. On the Configuration page the source already exists and secret fields are
        stripped from API responses — so the client can't supply them. This reads the
        stored (encrypted) credentials from the DB via the adapter instead.

        Body params: ``cdc_management_mode`` (``"posthog"`` | ``"self_managed"``),
        ``cdc_slot_name`` (optional), ``cdc_publication_name`` (optional).
        """
        instance: ExternalDataSource = self.get_object()

        adapter, err = self._get_cdc_adapter_or_400(instance)
        if err is not None:
            return err
        assert adapter is not None  # narrowed by _get_cdc_adapter_or_400

        management_mode = request.data.get("cdc_management_mode", "posthog")
        if management_mode not in ("posthog", "self_managed"):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "cdc_management_mode must be 'posthog' or 'self_managed'."},
            )

        schema_hint = (instance.job_inputs or {}).get("schema") or "public"
        try:
            prereq_errors = adapter.validate_prerequisites(
                instance,
                management_mode=management_mode,
                tables=[],
                schema=schema_hint,
                slot_name=request.data.get("cdc_slot_name") or None,
                publication_name=request.data.get("cdc_publication_name") or None,
            )
        except (OperationalError, BaseSSHTunnelForwarderError, SSLRequiredError) as e:
            # Probing the source's database to validate it is expected to fail when the host,
            # credentials, or SSH tunnel are wrong, the server requires/refuses SSL, or it drops the
            # connection. Surface it as a 400, but don't capture it — these are user/upstream
            # connection problems, not bugs in our code, and capturing every one floods error
            # tracking. Mirrors the detail=False check_cdc_prerequisites handler.
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to source to check prerequisites: {e}"},
            )
        except Exception as e:
            capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to source to check prerequisites: {e}"},
            )

        return Response(
            status=status.HTTP_200_OK,
            data={"valid": len(prereq_errors) == 0, "errors": prereq_errors},
        )

    @action(methods=["POST"], detail=True)
    def enable_cdc(self, request: Request, *arg: Any, **kwargs: Any):
        """Enable CDC on an existing source.

        Provisions engine-side CDC resources via the source's adapter, writes the CDC
        config into ``source.job_inputs``, and ensures the CDC extraction schedule
        exists. Re-runs prereq checks server-side so we never trust a stale
        client-side check.

        Body params: ``cdc_management_mode`` (``"posthog"`` | ``"self_managed"``),
        plus engine-specific identifier hints (e.g. ``cdc_slot_name``,
        ``cdc_publication_name`` for Postgres). Universal tuning fields:
        ``cdc_auto_drop_slot`` (optional bool), ``cdc_lag_warning_threshold_mb``
        (optional int), ``cdc_lag_critical_threshold_mb`` (optional int).
        """
        instance: ExternalDataSource = self.get_object()

        adapter, err = self._get_cdc_adapter_or_400(instance)
        if err is not None:
            return err
        assert adapter is not None  # narrowed by _get_cdc_adapter_or_400

        if not is_cdc_enabled_for_team(self.team):
            return Response(
                status=status.HTTP_403_FORBIDDEN,
                data={"message": "CDC is not enabled for this team."},
            )

        existing = adapter.parse_cdc_config(instance)
        if existing.enabled:
            return Response(
                status=status.HTTP_409_CONFLICT,
                data={"message": "CDC is already enabled on this source."},
            )

        management_mode = request.data.get("cdc_management_mode", "posthog")
        if management_mode not in ("posthog", "self_managed"):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "cdc_management_mode must be 'posthog' or 'self_managed'."},
            )

        # Validate prerequisites server-side — never trust a client-only check.
        schema_hint = (instance.job_inputs or {}).get("schema") or "public"
        try:
            prereq_errors = adapter.validate_prerequisites(
                instance,
                management_mode=management_mode,
                tables=[],
                schema=schema_hint,
                slot_name=request.data.get("cdc_slot_name") or None,
                publication_name=request.data.get("cdc_publication_name") or None,
            )
        except (OperationalError, BaseSSHTunnelForwarderError, SSLRequiredError) as e:
            # Expected user/upstream connection failure (bad host/credentials/SSH tunnel, server
            # requires/refuses SSL, dropped connection). Surface as a 400 without capturing — see the
            # check_cdc_prerequisites_for_source handler above.
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to source to check prerequisites: {e}"},
            )
        except Exception as e:
            capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to source to check prerequisites: {e}"},
            )

        if prereq_errors:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "CDC prerequisites not met.", "errors": prereq_errors},
            )

        cdc_error = self._setup_cdc_resources(adapter, instance, request.data)
        if cdc_error is not None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": cdc_error},
            )

        # Ensure the global cleanup schedule exists. There are no CDC schemas yet (the user
        # picks sync_type=cdc per schema afterward), so `sync_cdc_extraction_schedule` is a
        # no-op here — the extraction schedule is authoritatively (re)created when a schema is
        # switched to CDC. A failure here therefore can't leave a "CDC on, never runs" state:
        # the slot + config are valid and the schedule self-heals on the first CDC schema
        # toggle. Surface failures (capture, not just log) and flag them in the response.
        schedules_ok = True
        try:
            sync_cdc_extraction_schedule(instance, create=True)
            ensure_cdc_slot_cleanup_schedule()
        except Exception as e:
            schedules_ok = False
            logger.exception("Could not create CDC schedules after enable_cdc", exc_info=e)
            capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})

        return Response(status=status.HTTP_200_OK, data={"success": True, "schedules_ready": schedules_ok})

    @action(methods=["POST"], detail=True)
    def disable_cdc(self, request: Request, *arg: Any, **kwargs: Any):
        """Disable CDC on an existing source.

        Cancels any running CDC extraction workflow, deletes the extraction schedule,
        delegates engine-side teardown to the source's adapter (drops slot/publication
        for Postgres; equivalent for other engines), clears ``cdc_*`` keys from
        ``job_inputs``, soft-deletes companion CDC tables, and sets all CDC schemas to
        ``sync_type=None``, ``should_sync=False`` so the user must pick a new sync
        strategy before they resume.
        """
        instance: ExternalDataSource = self.get_object()

        adapter, err = self._get_cdc_adapter_or_400(instance)
        if err is not None:
            return err
        assert adapter is not None

        cdc_config = adapter.parse_cdc_config(instance)
        if not cdc_config.enabled:
            return Response(status=status.HTTP_200_OK, data={"success": True, "already_disabled": True})

        # Cancel running jobs for this source's CDC schemas — one holding the slot fails
        # pg_drop_replication_slot. Scope to CDC schemas so we don't cancel unrelated
        # incremental/full-refresh syncs on the same source. Read before the sync_type reset
        # below, while these schemas are still marked CDC.
        cdc_schema_ids = list(
            ExternalDataSchema.objects.filter(
                source=instance,
                sync_type=ExternalDataSchema.SyncType.CDC,
            )
            .exclude(deleted=True)
            .values_list("id", flat=True)
        )
        running_jobs = ExternalDataJob.objects.filter(
            pipeline_id=instance.pk,
            team_id=instance.team_id,
            status="Running",
            schema_id__in=cdc_schema_ids,
        ).exclude(workflow_id__isnull=True)
        for running_job in running_jobs:
            if not running_job.workflow_id:
                continue
            try:
                cancel_external_data_workflow(running_job.workflow_id)
            except Exception as e:
                capture_exception(e, {"source_id": str(instance.id), "workflow_id": running_job.workflow_id})

        # Generic schedule teardown: schedule lives on our side, independent of engine.
        try:
            delete_cdc_extraction_schedule(str(instance.id))
        except Exception:
            logger.exception("Failed to delete CDC extraction schedule", extra={"source_id": str(instance.id)})

        # Engine-side teardown: best-effort, never blocks the disable.
        try:
            adapter.cleanup_resources(instance)
        except Exception as e:
            logger.exception("Failed engine-side CDC cleanup during disable_cdc", exc_info=e)
            capture_exception(e, {"source_id": str(instance.id)})

        with transaction.atomic():
            # Clear any broken marker (recovery contract): leaving a stale cdc_broken in
            # sync_type_config would make CDC look broken the moment it's re-enabled.
            # Must be inside the atomic block so a failed schema-state reset rolls this back too.
            for schema_id in cdc_schema_ids:
                try:
                    update_sync_type_config_keys(schema_id, instance.team_id, removes=["cdc_broken"])
                except ExternalDataSchema.DoesNotExist:
                    pass

            # Force CDC schemas to pick a new strategy by clearing sync_type and pausing.
            ExternalDataSchema.objects.filter(
                source=instance,
                sync_type=ExternalDataSchema.SyncType.CDC,
            ).exclude(deleted=True).update(sync_type=None, should_sync=False)

            # Soft-delete `_cdc` companion DataWarehouseTable rows so the next sync
            # rebuilds them once the user picks a new strategy.
            DataWarehouseTable.objects.filter(
                external_data_source_id=instance.id,
                team_id=self.team_id,
                deleted=False,
                name__endswith="_cdc",
            ).update(deleted=True)

            # Clear ALL cdc_* keys from job_inputs — leaving stale engine identifiers
            # behind (e.g. `cdc_consistent_point`) would corrupt resume tracking if
            # CDC is later re-enabled.
            job_inputs = dict(instance.job_inputs or {})
            for key in list(job_inputs.keys()):
                if key.startswith("cdc_"):
                    job_inputs.pop(key, None)
            instance.job_inputs = job_inputs
            instance.save(update_fields=["job_inputs", "updated_at"])

        return Response(status=status.HTTP_200_OK, data={"success": True})

    @action(methods=["POST"], detail=True)
    def update_cdc_settings(self, request: Request, *arg: Any, **kwargs: Any):
        """Update CDC tuning fields without enabling/disabling.

        Lets users edit ``cdc_auto_drop_slot``, ``cdc_lag_warning_threshold_mb``, and
        ``cdc_lag_critical_threshold_mb`` independently. These fields are universal
        across engines. Engine-specific identifiers (slot name, management mode, …)
        are immutable post-enable — switching them requires disable + enable.
        """
        instance: ExternalDataSource = self.get_object()

        adapter, err = self._get_cdc_adapter_or_400(instance)
        if err is not None:
            return err
        assert adapter is not None

        cdc_config = adapter.parse_cdc_config(instance)
        if not cdc_config.enabled:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "CDC is not enabled on this source."},
            )

        job_inputs = dict(instance.job_inputs or {})
        updates: dict[str, Any] = {}

        if "cdc_auto_drop_slot" in request.data:
            updates["cdc_auto_drop_slot"] = bool(request.data["cdc_auto_drop_slot"])

        for field in ("cdc_lag_warning_threshold_mb", "cdc_lag_critical_threshold_mb"):
            if field in request.data:
                try:
                    value = int(request.data[field])
                except (TypeError, ValueError):
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": f"{field} must be an integer."},
                    )
                if value < 1:
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": f"{field} must be >= 1."},
                    )
                updates[field] = value

        warn = updates.get("cdc_lag_warning_threshold_mb", job_inputs.get("cdc_lag_warning_threshold_mb"))
        crit = updates.get("cdc_lag_critical_threshold_mb", job_inputs.get("cdc_lag_critical_threshold_mb"))
        if warn is not None and crit is not None and int(warn) >= int(crit):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Warning threshold must be less than critical threshold."},
            )

        if not updates:
            return Response(status=status.HTTP_200_OK, data={"success": True, "unchanged": True})

        job_inputs.update(updates)
        instance.job_inputs = job_inputs
        instance.save(update_fields=["job_inputs", "updated_at"])

        return Response(status=status.HTTP_200_OK, data={"success": True})

    @action(methods=["GET"], detail=True)
    def cdc_status(self, request: Request, *arg: Any, **kwargs: Any):
        """Live CDC health for an existing source: slot/publication existence and WAL lag.

        Reads from the source DB via the engine adapter. Returns ``{"enabled": false}``
        when CDC is off, or the stored config plus live ``slot_exists`` /
        ``publication_exists`` / ``lag_bytes`` when on. 400s if the source DB is
        unreachable so the UI can show a degraded/unreachable state.
        """
        instance: ExternalDataSource = self.get_object()

        adapter, err = self._get_cdc_adapter_or_400(instance)
        if err is not None:
            return err
        assert adapter is not None

        cdc_config = adapter.parse_cdc_config(instance)
        if not cdc_config.enabled:
            return Response(status=status.HTTP_200_OK, data={"enabled": False})

        try:
            live_status = adapter.get_status(instance)
        except Exception as e:
            capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to source to read CDC status: {e}"},
            )

        return Response(
            status=status.HTTP_200_OK,
            data={
                "enabled": True,
                "management_mode": cdc_config.management_mode,
                "slot_name": cdc_config.slot_name,
                "publication_name": cdc_config.publication_name,
                "lag_warning_threshold_mb": cdc_config.lag_warning_threshold_mb,
                "lag_critical_threshold_mb": cdc_config.lag_critical_threshold_mb,
                **live_status,
            },
        )

    @action(methods=["POST"], detail=False)
    def source_prefix(self, request: Request, *arg: Any, **kwargs: Any):
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]
        access_method = request.data.get("access_method", ExternalDataSource.AccessMethod.WAREHOUSE)

        if access_method == ExternalDataSource.AccessMethod.DIRECT:
            if source_type not in direct_capable_source_types():
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": DIRECT_QUERY_UNSUPPORTED_SOURCE_MESSAGE},
                )

            normalized_prefix = prefix.strip() if isinstance(prefix, str) else ""
            if not normalized_prefix:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Name is required for direct query sources"},
                )

            return Response(status=status.HTTP_200_OK)

        if not prefix:
            if self.prefix_required(source_type):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Source type already exists. Prefix is required"},
                )
        elif self.prefix_exists(source_type, prefix):
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Prefix already exists"})

        return Response(status=status.HTTP_200_OK)

    @action(methods=["GET"], detail=True, pagination_class=None)
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="after",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="ISO timestamp — only return jobs created after this date.",
            ),
            OpenApiParameter(
                name="before",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="ISO timestamp — only return jobs created before this date.",
            ),
            OpenApiParameter(
                name="schemas",
                type={"type": "array", "items": {"type": "string"}},
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter jobs by table schema names.",
            ),
        ],
        responses=ExternalDataJobSerializers(many=True),
    )
    def jobs(self, request: Request, *arg: Any, **kwargs: Any):
        instance: ExternalDataSource = self.get_object()
        after = request.query_params.get("after", None)
        before = request.query_params.get("before", None)
        schemas = request.query_params.getlist("schemas")

        # select_related joins the full ExternalDataSchema row; defer its large JSON/text
        # columns so the serializer only pulls the fields SimpleExternalDataSchemaSerializer
        # actually reads (sync_type_config + latest_error can each be sizeable).
        jobs = (
            instance.jobs.filter(billable=True)
            .select_related("schema")
            .defer("schema__sync_type_config", "schema__latest_error")
            .order_by("-created_at")
        )

        if schemas:
            jobs = jobs.filter(schema__name__in=schemas)
        if after:
            after_date = parser.parse(after)
            jobs = jobs.filter(created_at__gt=after_date)
        if before:
            before_date = parser.parse(before)
            jobs = jobs.filter(created_at__lt=before_date)

        jobs = jobs[:50]

        return Response(
            status=status.HTTP_200_OK,
            data=ExternalDataJobSerializers(
                jobs, many=True, read_only=True, context=self.get_serializer_context()
            ).data,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="source_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Comma-separated source type(s) to return config for, e.g. 'Postgres' or "
                    "'Postgres,Stripe'. Strongly recommended: the unfiltered response describes every "
                    "supported source and is very large. Omit only to enumerate the available types."
                ),
            )
        ],
    )
    @action(methods=["GET"], detail=False)
    def wizard(self, request: Request, *arg: Any, **kwargs: Any):
        configs = build_source_configs()

        requested = request.query_params.get("source_type")
        if requested:
            requested_types = [t.strip() for t in requested.split(",") if t.strip()]
            unknown = [t for t in requested_types if t not in configs]
            if unknown:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": f"Unknown source_type(s): {', '.join(sorted(unknown))}. "
                        "Omit source_type to list every available type."
                    },
                )
            configs = {st: config for st, config in configs.items() if st in requested_types}

        return Response(status=status.HTTP_200_OK, data=configs)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="source_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="The source type to generate a connect link for (e.g. 'Stripe', 'Postgres', 'Hubspot').",
            )
        ],
        responses=SourceConnectLinkSerializer,
    )
    @action(methods=["GET"], detail=False)
    def connect_link(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return a secure browser link for connecting a data warehouse source.

        The link opens a minimal connect page rendering the source's full connection form — OAuth options
        included — with no table selection and no source creation. The user authenticates in their browser,
        secrets never pass through the agent, and the agent finishes setup afterwards by passing the stored
        credential id to data-warehouse-source-setup.
        """
        source_type = request.query_params.get("source_type")
        if not source_type:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Missing required parameter: source_type"},
            )
        try:
            source_type_model = ExternalDataSourceType(source_type)
        except ValueError:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Unknown source_type '{source_type}'"},
            )

        source = SourceRegistry.get_source(source_type_model)
        oauth_field = _find_top_level_oauth_field(source.get_source_config.model_dump())
        action_phrase = (
            f"connect their {source_type} account" if oauth_field else f"enter their {source_type} connection details"
        )

        data = {
            "source_type": source_type,
            "auth_method": "oauth" if oauth_field else "credentials",
            "connect_url": (
                f"{settings.SITE_URL}/project/{self.team_id}/data-warehouse/connect?kind={quote(str(source_type))}"
            ),
            "instructions": (
                f"Share this link with the user. They {action_phrase} directly in PostHog — never ask them to "
                "paste credentials or tokens into the chat. The page only stores the connection details; it does "
                "not create the source. Once the user confirms they're done, find the stored credential id via "
                f"data-warehouse-stored-credentials-list (source_type='{source_type}', newest first) and call "
                'data-warehouse-source-setup with {"credential_id": <id>} in the payload. Stored credentials are '
                "single-use and expire after 24 hours."
            ),
        }
        return Response(status=status.HTTP_200_OK, data=SourceConnectLinkSerializer(data).data)

    @extend_schema(responses=ExternalDataSourceConnectionOptionSerializer(many=True))
    @action(methods=["GET"], detail=False)
    def connections(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = (
            ExternalDataSource._base_manager.filter(
                team_id=self.team_id,
                access_method=ExternalDataSource.AccessMethod.DIRECT,
                source_type__in=direct_capable_source_types(),
            )
            .exclude(deleted=True)
            .only("id", "prefix", "connection_metadata")
            .order_by(self.ordering)
        )
        queryset = self.user_access_control.filter_queryset_by_access_level(queryset)

        serializer = ExternalDataSourceConnectionOptionSerializer(queryset, many=True)
        return Response(status=status.HTTP_200_OK, data=serializer.data)

    @action(methods=["PATCH"], detail=True)
    def revenue_analytics_config(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Update the revenue analytics configuration and return the full external data source."""
        external_data_source = self.get_object()
        config = external_data_source.revenue_analytics_config_safe

        config_serializer = ExternalDataSourceRevenueAnalyticsConfigSerializer(config, data=request.data, partial=True)
        config_serializer.is_valid(raise_exception=True)
        config_serializer.save()

        table_prefix = external_data_source.prefix or ""

        if config.enabled:
            managed_viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
                team=self.team,
                kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
            )
            managed_viewset.sync_views()
            ensure_person_join(self.team.pk, table_prefix)
        else:
            try:
                managed_viewset = DataWarehouseManagedViewSet.objects.get(
                    team=self.team,
                    kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
                )
                managed_viewset.delete_with_views()

            except DataWarehouseManagedViewSet.DoesNotExist:
                pass
            remove_person_join(self.team.pk, table_prefix)

        # Return the full external data source with updated config
        source_serializer = self.get_serializer(external_data_source, context=self.get_serializer_context())
        return Response(source_serializer.data)

    def _compute_missing_webhook_events(
        self,
        source: WebhookSource,
        config: Any,
        instance: ExternalDataSource,
        external_status: ExternalWebhookInfo | None,
    ) -> list[str]:
        """Desired events not yet on the provider webhook — surfaced so manual-webhook users
        (or keys lacking webhook-write scope) know what to add."""
        if not external_status or not external_status.exists or external_status.error:
            return []

        eligible_schema_names = list(
            ExternalDataSchema.objects.filter(
                source=instance,
                team_id=self.team_id,
                sync_type=ExternalDataSchema.SyncType.WEBHOOK,
                should_sync=True,
            )
            .exclude(deleted=True)
            .values_list("name", flat=True)
        )

        desired = source.get_desired_webhook_events(config, eligible_schema_names)
        if not desired:
            return []

        current = set(external_status.enabled_events or [])
        if "*" in current:
            return []

        return sorted(e for e in desired if e not in current)

    @action(methods=["GET"], detail=True)
    def webhook_info(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()
        source_type = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type)

        if not isinstance(source, WebhookSource):
            return Response(
                status=status.HTTP_200_OK,
                data={
                    "supports_webhooks": False,
                    "exists": False,
                    "webhook_url": None,
                    "schema_mapping": {},
                    "external_status": None,
                },
            )

        hog_function = HogFunction.objects.filter(
            team=self.team,
            type="warehouse_source_webhook",
            inputs__source_id__value=str(instance.pk),
            deleted=False,
        ).first()

        if not hog_function:
            return Response(
                status=status.HTTP_200_OK,
                data={"supports_webhooks": True, "exists": False},
            )

        webhook_url = get_webhook_url(hog_function.id)

        external_status: ExternalWebhookInfo | None = None
        missing_events: list[str] = []

        if instance.job_inputs:
            try:
                config = source.parse_config(instance.job_inputs)
                external_status = source.get_external_webhook_info(config, webhook_url, self.team_id)
                missing_events = self._compute_missing_webhook_events(source, config, instance, external_status)
            except Exception as e:
                capture_exception(e)

        schema_mapping = {}
        if hog_function.inputs:
            schema_mapping = hog_function.inputs.get("schema_mapping", {}).get("value", {})

        webhook_field_names = {f.name for f in (source.get_source_config.webhookFields or [])}
        all_inputs = HogFunctionSerializer(hog_function).data.get("inputs") or {}
        webhook_inputs = {k: v for k, v in all_inputs.items() if k in webhook_field_names}

        return Response(
            status=status.HTTP_200_OK,
            data={
                "supports_webhooks": True,
                "exists": True,
                "hog_function": {
                    "id": str(hog_function.id),
                    "name": hog_function.name,
                    "enabled": hog_function.enabled,
                    "created_at": hog_function.created_at.isoformat(),
                    "status": hog_function.status,
                },
                "webhook_url": webhook_url,
                "schema_mapping": schema_mapping,
                "inputs": webhook_inputs,
                "external_status": dataclasses.asdict(external_status) if external_status else None,
                "missing_events": missing_events,
            },
        )

    @action(methods=["POST"], detail=True)
    def create_webhook(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()

        if not instance.job_inputs:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Source has no configuration"},
            )

        source_type = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type)

        if not isinstance(source, WebhookSource):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "This source type does not support webhooks"},
            )

        try:
            config = source.parse_config(instance.job_inputs)
            source_schemas = source.get_schemas(config, self.team_id)
        except ValidationError as e:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Invalid source configuration", "details": getattr(e, "detail", str(e))},
            )
        except Exception as e:
            capture_exception(e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Failed to load source configuration or schemas"},
            )

        webhook_source_schemas = {s.name: s for s in source_schemas if s.supports_webhooks}

        db_schemas = ExternalDataSchema.objects.filter(
            source=instance,
            team_id=self.team_id,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            should_sync=True,
        ).exclude(deleted=True)

        eligible_schemas = [s for s in db_schemas if s.name in webhook_source_schemas]

        hog_fn_result = get_or_create_webhook_hog_function(
            team=self.team,
            source=source,
            source_id=str(instance.pk),
            eligible_schemas=eligible_schemas,
        )

        if hog_fn_result.error:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": hog_fn_result.error},
            )

        result = create_and_register_webhook(source, config, hog_fn_result, self.team_id)

        return Response(
            status=status.HTTP_200_OK,
            data={
                "success": result.success,
                "webhook_url": result.webhook_url,
                "error": result.error,
                "pending_inputs": result.pending_inputs,
            },
        )

    @action(methods=["POST"], detail=True)
    def update_webhook_inputs(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()

        if not instance.job_inputs:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Source has no configuration"},
            )

        source_type = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type)

        if not isinstance(source, WebhookSource):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "This source type does not support webhooks"},
            )

        inputs = request.data.get("inputs", {})
        if not inputs or not isinstance(inputs, dict):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "No inputs provided"},
            )

        source_config = source.get_source_config
        webhook_fields = source_config.webhookFields or []
        webhook_field_names = {f.name for f in webhook_fields}

        invalid_keys = set(inputs.keys()) - webhook_field_names
        if invalid_keys:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid input keys: {', '.join(invalid_keys)}"},
            )

        required_fields = [f.name for f in webhook_fields if getattr(f, "required", False)]
        blanked_required = [name for name in required_fields if name in inputs and not inputs[name]]
        if blanked_required:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Missing required fields: {', '.join(blanked_required)}"},
            )

        try:
            hog_function = HogFunction.objects.get(
                team=self.team,
                type="warehouse_source_webhook",
                inputs__source_id__value=str(instance.pk),
                deleted=False,
            )
        except HogFunction.DoesNotExist:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "No webhook function found for this source. Create a webhook first."},
            )

        try:
            config = source.parse_config(instance.job_inputs)
        except ValidationError as e:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Invalid source configuration", "details": getattr(e, "detail", str(e))},
            )
        except Exception as e:
            capture_exception(e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Failed to load source configuration"},
            )

        assert hog_function.inputs is not None
        hog_function.inputs = {
            **hog_function.inputs,
            **{key: {"value": value} for key, value in inputs.items()},
        }
        hog_function.save(update_fields=["inputs", "encrypted_inputs"])

        success, error = source.webhook_inputs_updated(config, get_webhook_url(hog_function.id), self.team.pk, inputs)
        if not success:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"success": False, "error": error or "Failed to update webhook on the external source."},
            )

        return Response(status=status.HTTP_200_OK, data={"success": True})

    @extend_schema(
        request=ExternalDataSourceBulkUpdateSchemasSerializer,
        responses={200: ExternalDataSchemaSerializer(many=True)},
    )
    @action(methods=["PATCH"], detail=True)
    def bulk_update_schemas(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source = self.get_object()
        serializer = ExternalDataSourceBulkUpdateSchemasSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        schema_updates: list[dict[str, Any]] = serializer.validated_data["schemas"]
        schema_ids = [schema_update["id"] for schema_update in schema_updates]

        if len(set(schema_ids)) != len(schema_ids):
            raise ValidationError("Schema updates must contain unique ids")

        source_schemas = ExternalDataSchema.objects.filter(
            team_id=self.team_id,
            source_id=source.id,
            id__in=schema_ids,
        ).select_related("source", "table__credential", "table__external_data_source")
        source_schemas_by_id = {schema.id: schema for schema in source_schemas}

        if len(source_schemas_by_id) != len(schema_ids):
            raise ValidationError("One or more schemas could not be found for this source")

        serializer_context = self.get_serializer_context()
        updated_schemas: list[ExternalDataSchema] = []
        # Each deferred action is paired with its schema so a post-commit failure can be attributed.
        post_commit_actions: list[tuple[ExternalDataSchema, Callable[[], None]]] = []

        # Validate every payload before writing anything, so a malformed request is rejected up
        # front. Some checks only run inside the serializer's update() (during save() below), so
        # this catches the common input errors but not all of them — the save loop handles the rest.
        prepared: list[tuple[ExternalDataSchema, ExternalDataSchemaSerializer, list[Callable[[], None]]]] = []
        for schema_update in schema_updates:
            schema_id = schema_update["id"]
            schema = source_schemas_by_id[schema_id]
            schema_payload = {key: value for key, value in schema_update.items() if key != "id"}

            schema_post_commit_actions: list[Callable[[], None]] = []
            schema_serializer = ExternalDataSchemaSerializer(
                schema,
                data=schema_payload,
                partial=True,
                context={**serializer_context, "post_commit_actions": schema_post_commit_actions},
            )
            schema_serializer.is_valid(raise_exception=True)
            # Do the webhook-only source-discovery call (e.g. Google Ads token refresh + field query)
            # here, before the per-schema transaction below. Running it inside update()'s transaction
            # held the DB connection idle-in-transaction long enough for the server to close it.
            # update() reads the cached result, so it still validates and fails per-schema.
            schema_serializer.warm_webhook_only_check(schema)
            prepared.append((schema, schema_serializer, schema_post_commit_actions))

        # Commit each schema in its own transaction. A single atomic block around the whole batch
        # meant one schema's failure rolled back every schema and failed the request, so the user
        # got nothing applied. Isolating per schema keeps the ones that saved committed, attempts
        # every schema so a single bad one can't block the rest, and reports the failures together.
        failed_schemas: dict[str, tuple[str, str]] = {}
        only_validation_errors = True
        for schema, schema_serializer, schema_post_commit_actions in prepared:
            try:
                with transaction.atomic():
                    updated_schemas.append(schema_serializer.save())
            except Exception as e:
                if isinstance(e, ValidationError):
                    reason = _validation_error_message(e)
                    logger.warning(
                        "bulk_update_schemas validation error during save",
                        source_id=str(source.id),
                        schema_id=str(schema.id),
                    )
                else:
                    only_validation_errors = False
                    reason = "a database error occurred while saving"
                    capture_exception(e)
                    logger.exception(
                        "bulk_update_schemas failed to persist schema",
                        source_id=str(source.id),
                        schema_id=str(schema.id),
                    )
                failed_schemas[str(schema.id)] = (schema.name, reason)
                # A dropped connection leaves Django holding a dead handle; reset it so the next
                # schema reconnects instead of failing on the same broken connection.
                if not connection.is_usable():
                    connection.close()
                continue

            # Only run a schema's Temporal side effects once its own row is committed.
            post_commit_actions.extend((schema, action) for action in schema_post_commit_actions)

        post_commit_error: Exception | None = None
        for action_schema, post_commit_action in post_commit_actions:
            try:
                post_commit_action()
            except Exception as e:
                # The row is already committed but its schedule still runs the old cadence. Capture +
                # log every failure (with the schema id) so the drift is visible, and remember it so
                # the request fails below — the caller must know the batch did not fully apply.
                post_commit_error = e
                capture_exception(e)
                logger.warning(
                    "bulk_update_schemas saved the schema but its Temporal schedule update failed",
                    source_id=str(source.id),
                    schema_id=str(action_schema.id),
                    exc_info=e,
                )

        # Report save failures first so a schedule-update failure can't mask which schemas didn't
        # save, then fail the request on the schedule-update failure.
        if failed_schemas:
            raise BulkSchemaSaveError(failed_schemas, only_validation_errors=only_validation_errors)
        if post_commit_error is not None:
            raise post_commit_error

        return Response(
            ExternalDataSchemaSerializer(updated_schemas, many=True, context=serializer_context).data,
            status=status.HTTP_200_OK,
        )

    @action(methods=["POST"], detail=True)
    def delete_webhook(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()

        source_type = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type)

        if not isinstance(source, WebhookSource):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "This source type does not support webhooks"},
            )

        # Check that no schemas are still relying on the webhook — deleting it
        # would break their sync pipeline.
        webhook_schemas = ExternalDataSchema.objects.filter(
            source=instance,
            team_id=self.team_id,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            should_sync=True,
        ).exclude(deleted=True)

        if webhook_schemas.exists():
            schema_names = list(webhook_schemas.values_list("name", flat=True))
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "message": f"Cannot delete webhook while tables are using webhook sync: {', '.join(schema_names)}. Switch them to full refresh, incremental, or disable syncing first.",
                },
            )

        if not instance.job_inputs:
            # No config means we can't call the external API, but we can still
            # clean up the HogFunction.
            try:
                hog_function = HogFunction.objects.get(
                    team=self.team,
                    type="warehouse_source_webhook",
                    inputs__source_id__value=str(instance.pk),
                    deleted=False,
                )
                hog_function.deleted = True
                hog_function.enabled = False
                hog_function.save(update_fields=["deleted", "enabled"])
            except HogFunction.DoesNotExist:
                pass

            return Response(
                status=status.HTTP_200_OK,
                data={"success": True, "external_deleted": False},
            )

        try:
            config = source.parse_config(instance.job_inputs)
        except Exception as e:
            capture_exception(e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Failed to parse source configuration"},
            )

        result = delete_webhook_and_hog_function(
            team=self.team,
            source=source,
            config=config,
            source_id=str(instance.pk),
        )

        return Response(
            status=status.HTTP_200_OK,
            data={
                "success": result.success,
                "external_deleted": result.external_deleted,
                "error": result.error,
            },
        )
