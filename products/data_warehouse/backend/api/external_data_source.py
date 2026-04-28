from __future__ import annotations

import uuid
import dataclasses
from collections.abc import Callable
from datetime import timedelta
from typing import Any, cast

from django.db import transaction
from django.db.models import Prefetch, Q

import structlog
import temporalio
from dateutil import parser
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import filters, serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import (
    ProductKey,
    SourceFieldFileUploadConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)

from posthog.hogql.database.database import Database

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.activity_logging.external_data_utils import (
    get_external_data_source_created_by_info,
    get_external_data_source_detail_name,
)
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.temporal.data_imports.sources import SourceRegistry
from posthog.temporal.data_imports.sources.common.base import ExternalWebhookInfo, FieldType, WebhookSource
from posthog.temporal.data_imports.sources.common.config import Config
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.postgres.cdc.config import PostgresCDCConfig
from posthog.temporal.data_imports.sources.postgres.source import PostgresSource

from products.data_warehouse.backend.api.external_data_schema import (
    ExternalDataSchemaSerializer,
    SimpleExternalDataSchemaSerializer,
)
from products.data_warehouse.backend.data_load.service import (
    cancel_external_data_workflow,
    delete_external_data_schedule,
    is_any_external_data_schema_paused,
    is_cdc_enabled_for_team,
    sync_external_data_job_workflow,
    trigger_external_data_source_workflow,
)
from products.data_warehouse.backend.direct_postgres import (
    get_direct_postgres_location,
    postgres_schema_metadata,
    reconcile_direct_postgres_schemas,
    rename_direct_postgres_schemas_to_match_source_schemas,
    upsert_direct_postgres_table,
)
from products.data_warehouse.backend.external_data_source.webhooks import (
    create_and_register_webhook,
    delete_webhook_and_hog_function,
    get_or_create_webhook_hog_function,
    get_webhook_url,
)
from products.data_warehouse.backend.models import (
    DataWarehouseManagedViewSet,
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.data_warehouse.backend.models.external_data_schema import sync_old_schemas_with_new_schemas
from products.data_warehouse.backend.models.revenue_analytics_config import ExternalDataSourceRevenueAnalyticsConfig
from products.data_warehouse.backend.models.util import postgres_columns_to_dwh_columns, validate_source_prefix
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind, ExternalDataSourceType
from products.revenue_analytics.backend.joins import ensure_person_join, remove_person_join

logger = structlog.get_logger(__name__)


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


def get_direct_postgres_connection_metadata(
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

    from posthog.temporal.data_imports.sources.postgres.postgres import source_requires_ssl

    require_ssl = source_model is not None and source_requires_ssl(source_model, source_config)

    try:
        metadata = metadata_fetcher(source_config, team_id, require_ssl=require_ssl)
    except Exception as error:
        capture_exception(error)
        return fallback or {}

    return metadata if isinstance(metadata, dict) else (fallback or {})


def get_postgres_source_table_location(
    *,
    schema_name: str,
    source_schema: SourceSchema | None,
    default_schema: str | None,
) -> tuple[str | None, str, str]:
    return get_direct_postgres_location(
        schema_name=schema_name,
        schema_metadata={
            "source_catalog": source_schema.source_catalog if source_schema else None,
            "source_schema": source_schema.source_schema if source_schema else None,
            "source_table_name": source_schema.source_table_name if source_schema else None,
        },
        default_schema=default_schema,
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
        choices=["duckdb", "postgres"],
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
        choices=["duckdb", "postgres"],
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
        help_text="Requested sync mode for the schema.",
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


class ExternalDataSourceBulkUpdateSchemasSerializer(serializers.Serializer):
    schemas = ExternalDataSourceBulkUpdateSchemaSerializer(
        many=True,
        allow_empty=False,
        help_text="Schema updates to apply in a single batch.",
    )


class ExternalDataJobSerializers(serializers.ModelSerializer):
    schema = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)

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
        ]

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
        choices=["duckdb", "postgres"],
        help_text="Backend engine detected for the direct connection.",
    )
    revenue_analytics_config = ExternalDataSourceRevenueAnalyticsConfigSerializer(
        source="revenue_analytics_config_safe", read_only=True
    )
    access_method = serializers.ChoiceField(choices=ExternalDataSource.AccessMethod.choices, read_only=True)
    supports_webhooks = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ExternalDataSource
        fields = [
            "id",
            "created_at",
            "created_by",
            "status",
            "client_secret",
            "account_id",
            "source_type",
            "latest_error",
            "prefix",
            "description",
            "access_method",
            "engine",
            "last_run_at",
            "schemas",
            "job_inputs",
            "revenue_analytics_config",
            "user_access_level",
            "supports_webhooks",
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

    def get_status(self, instance: ExternalDataSource) -> str:
        active_schemas: list[ExternalDataSchema] = list(instance.active_schemas)  # type: ignore
        any_failures = any(schema.status == ExternalDataSchema.Status.FAILED for schema in active_schemas)
        any_billing_limits_reached = any(
            schema.status == ExternalDataSchema.Status.BILLING_LIMIT_REACHED for schema in active_schemas
        )
        any_billing_limits_too_low = any(
            schema.status == ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW for schema in active_schemas
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
        incoming_prefix = validated_data.get("prefix", instance.prefix)

        if instance.is_direct_postgres:
            # For direct Postgres sources the prefix acts as the user-facing source name.
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
            # Deep-merge: start with existing, overlay incoming top-level keys
            merged_ssh_tunnel = {**existing_ssh_tunnel, **incoming_ssh_tunnel}

            # Check both 'auth' (new format) and 'auth_type' (legacy format from migration 0807)
            existing_auth = (
                (existing_ssh_tunnel or {}).get("auth") or (existing_ssh_tunnel or {}).get("auth_type") or {}
            )
            incoming_auth = (
                (incoming_ssh_tunnel or {}).get("auth") or (incoming_ssh_tunnel or {}).get("auth_type") or {}
            )

            if not incoming_auth:
                # No auth in incoming request - preserve entire existing auth
                merged_ssh_tunnel["auth"] = {**existing_auth}
            else:
                # Merge auth, preserving sensitive fields not explicitly provided
                merged_auth = {**incoming_auth}
                for key in ("password", "passphrase", "private_key"):
                    if existing_auth.get(key) and not incoming_auth.get(key):
                        merged_auth[key] = existing_auth[key]
                merged_ssh_tunnel["auth"] = merged_auth

            new_job_inputs["ssh_tunnel"] = merged_ssh_tunnel

        is_valid, errors = source.validate_config(new_job_inputs)
        if not is_valid:
            raise ValidationError(f"Invalid source config: {', '.join(errors)}")

        source_config: Config = source.parse_config(new_job_inputs)
        validated_data["job_inputs"] = source_config.to_dict()

        if job_inputs_were_submitted:
            if instance.source_type == ExternalDataSourceType.POSTGRES and isinstance(source, PostgresSource):
                credentials_valid, credentials_error = source.validate_credentials_for_access_method(
                    cast(Any, source_config), instance.team_id, instance.access_method
                )
            else:
                credentials_valid, credentials_error = source.validate_credentials(source_config, instance.team_id)
            if not credentials_valid:
                raise ValidationError(credentials_error or "Invalid credentials")
            if instance.is_direct_postgres:
                discovered_schemas = source.get_schemas(source_config, instance.team_id)
                validated_data["connection_metadata"] = get_direct_postgres_connection_metadata(
                    source_impl=source,
                    source_config=source_config,
                    team_id=instance.team_id,
                    source_model=instance,
                    fallback=instance.connection_metadata,
                )

        updated_source: ExternalDataSource = super().update(instance, validated_data)

        if updated_source.is_direct_postgres and discovered_schemas is not None:
            schema_names = {schema.name: schema.label for schema in discovered_schemas}
            descriptions = {schema.name: schema.description for schema in discovered_schemas}

            with transaction.atomic():
                ExternalDataSource._base_manager.filter(pk=updated_source.pk).select_for_update().get()
                rename_direct_postgres_schemas_to_match_source_schemas(
                    source=updated_source,
                    source_schemas=discovered_schemas,
                    team_id=instance.team_id,
                )
                sync_old_schemas_with_new_schemas(
                    schema_names,
                    source_id=str(updated_source.id),
                    team_id=instance.team_id,
                    descriptions=descriptions,
                )
                reconcile_direct_postgres_schemas(
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


class DatabaseSchemaRequestSerializer(serializers.Serializer):
    """Validate credentials and preview available tables from a remote database.

    The request body contains source_type plus flat source-specific credential fields
    (e.g. host, port, database, user, password, schema for Postgres). The credential
    fields vary per source_type and are validated dynamically by the source registry.
    """

    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type to validate against.",
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


@extend_schema(tags=[ProductKey.DATA_WAREHOUSE])
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
        "source_prefix",
        "revenue_analytics_config",
        "create_webhook",
        "update_webhook_inputs",
        "delete_webhook",
        "check_cdc_prerequisites",
    ]
    scope_object_read_actions = ["list", "retrieve", "jobs", "wizard", "webhook_info", "connections"]
    queryset = ExternalDataSource.objects.all()
    serializer_class = ExternalDataSourceSerializers
    filter_backends = [filters.SearchFilter]
    search_fields = ["source_id"]
    ordering = "-created_at"

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.action == "create":
            return ExternalDataSourceCreateSerializer
        if self.action == "database_schema":
            return DatabaseSchemaRequestSerializer
        return ExternalDataSourceSerializers

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["database"] = Database.create_for(team_id=self.team_id)

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

        prefix = serializer.validated_data.get("prefix")
        description = serializer.validated_data.get("description")
        source_type = serializer.validated_data["source_type"]
        access_method = serializer.validated_data.get("access_method", ExternalDataSource.AccessMethod.WAREHOUSE)
        is_direct_postgres = (
            access_method == ExternalDataSource.AccessMethod.DIRECT and source_type == ExternalDataSourceType.POSTGRES
        )

        if access_method == ExternalDataSource.AccessMethod.DIRECT and source_type != ExternalDataSourceType.POSTGRES:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Direct query mode is currently supported only for Postgres sources."},
            )

        if is_direct_postgres:
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

            if self.prefix_required(source_type):
                if not prefix:
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": "Source type already exists. Prefix is required"},
                    )
                if self.prefix_exists(source_type, prefix):
                    return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Prefix already exists"})

        if access_method == ExternalDataSource.AccessMethod.WAREHOUSE and is_any_external_data_schema_paused(
            self.team_id
        ):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please increase your billing limit to resume syncing."},
            )

        # Strip leading and trailing whitespace
        payload = serializer.validated_data["payload"]
        if payload is not None:
            for key, value in payload.items():
                if isinstance(value, str):
                    payload[key] = value.strip()
        source_type_model = ExternalDataSourceType(source_type)
        source = SourceRegistry.get_source(source_type_model)
        is_valid, errors = source.validate_config(payload)
        if not is_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid source config: {', '.join(errors)}"},
            )
        source_config: Config = source.parse_config(payload)

        if source_type_model == ExternalDataSourceType.POSTGRES and isinstance(source, PostgresSource):
            credentials_valid, credentials_error = source.validate_credentials_for_access_method(
                cast(Any, source_config), self.team_id, access_method
            )
        else:
            credentials_valid, credentials_error = source.validate_credentials(source_config, self.team_id)
        if not credentials_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": credentials_error or "Invalid credentials"},
            )

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            created_by=request.user if isinstance(request.user, User) else None,
            team=self.team,
            status="Running",
            source_type=source_type_model,
            job_inputs=source_config.to_dict(),
            prefix=prefix,
            description=description,
            access_method=access_method,
        )

        # CDC: create slot + publication for PostHog-managed sources
        cdc_enabled = payload.get("cdc_enabled", False) and is_cdc_enabled_for_team(self.team)
        if cdc_enabled and source_type_model == ExternalDataSourceType.POSTGRES:
            cdc_result = self._setup_cdc_slot(source, source_config, new_source_model, payload)
            if cdc_result is not None:
                return cdc_result

        source_schemas = source.get_schemas(source_config, self.team_id)
        if is_direct_postgres:
            new_source_model.connection_metadata = get_direct_postgres_connection_metadata(
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

        active_schemas: list[ExternalDataSchema] = []

        # Pre-fetch PK column names for CDC tables
        pk_columns_by_table: dict[str, list[str]] = {}
        if cdc_enabled and source_type_model == ExternalDataSourceType.POSTGRES:
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
                from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import cdc_pg_connection
                from posthog.temporal.data_imports.sources.postgres.postgres import get_primary_key_columns

                with cdc_pg_connection(new_source_model) as conn:
                    for db_schema, cdc_table_names in cdc_table_names_by_schema.items():
                        queried_pks = get_primary_key_columns(conn, db_schema, list(cdc_table_names))
                        for table_name, primary_key_columns in queried_pks.items():
                            schema_name = cdc_schema_name_by_location.get((db_schema, table_name))
                            if schema_name is not None:
                                pk_columns_by_table[schema_name] = primary_key_columns

        # Create all ExternalDataSchema objects and enable syncing for active schemas
        for schema in payload_schemas:
            sync_type = schema.get("sync_type")
            requires_incremental_fields = sync_type == "incremental" or sync_type == "append"
            incremental_field = schema.get("incremental_field")
            incremental_field_type = schema.get("incremental_field_type")
            primary_key_columns = schema.get("primary_key_columns")
            sync_time_of_day = schema.get("sync_time_of_day")
            should_sync = schema.get("should_sync", False)

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
            resolved_source_catalog, resolved_source_schema, resolved_source_table_name = (
                get_postgres_source_table_location(
                    schema_name=schema_name,
                    source_schema=source_schema,
                    default_schema=default_source_schema,
                )
            )
            resolved_source_catalog, resolved_source_schema, resolved_source_table_name = get_direct_postgres_location(
                schema_name=schema_name,
                schema_metadata={
                    "source_catalog": source_schema.source_catalog if source_schema else None,
                    "source_schema": source_schema.source_schema if source_schema else None,
                    "source_table_name": source_schema.source_table_name if source_schema else None,
                },
                default_schema=default_source_schema,
            )
            schema_metadata = (
                postgres_schema_metadata(
                    source_schema.columns if source_schema else [],
                    source_schema.foreign_keys if source_schema else [],
                    source_catalog=resolved_source_catalog,
                    source_schema=resolved_source_schema,
                    source_table_name=resolved_source_table_name,
                )
                if source_type_model == ExternalDataSourceType.POSTGRES
                else {}
            )

            is_cdc_schema = sync_type == "cdc"
            if requires_incremental_fields and new_source_model.supports_scheduled_sync:
                # If the caller didn't provide primary_key_columns, fall back to whatever the
                # source detected during schema discovery. Otherwise we rely on sync-time
                # re-detection, which can disagree with discovery (e.g. permissions differences
                # across query paths) and leave incremental syncs without a primary key.
                effective_primary_key_columns = primary_key_columns or (
                    source_schema.detected_primary_keys if source_schema else None
                )
                sync_type_config = {
                    "incremental_field": incremental_field,
                    "incremental_field_type": incremental_field_type,
                    "schema_metadata": schema_metadata,
                    **({"primary_key_columns": effective_primary_key_columns} if effective_primary_key_columns else {}),
                }
            elif is_cdc_schema:
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
                if is_cdc_schema and new_source_model.supports_scheduled_sync
                else timedelta(hours=6)
            )
            schema_model = ExternalDataSchema.objects.create(
                name=schema_name,
                team=self.team,
                source=new_source_model,
                should_sync=should_sync,
                sync_type=sync_type if new_source_model.supports_scheduled_sync else None,
                sync_time_of_day=sync_time_of_day if new_source_model.supports_scheduled_sync else None,
                sync_type_config=sync_type_config,
                description=source_schema.description if source_schema else None,
                label=schema_label_by_name.get(schema_name),
                sync_frequency_interval=schema_sync_frequency_interval,
            )

            # For CDC schemas with PostHog-managed mode, add table to publication
            if is_cdc_schema and should_sync and cdc_enabled:
                cdc_config = PostgresCDCConfig.from_source(new_source_model)
                if cdc_config.management_mode == "posthog" and cdc_config.publication_name:
                    self._add_table_to_cdc_publication(
                        new_source_model,
                        cdc_config.publication_name,
                        resolved_source_schema,
                        resolved_source_table_name,
                    )

            if new_source_model.is_direct_postgres and should_sync:
                schema_model.table = upsert_direct_postgres_table(
                    None,
                    schema_name=schema_name,
                    source=new_source_model,
                    columns=postgres_columns_to_dwh_columns(source_schema.columns if source_schema else []),
                    source_catalog=resolved_source_catalog,
                    source_schema=resolved_source_schema,
                    source_table_name=resolved_source_table_name,
                )
                schema_model.save(update_fields=["table"])

            if should_sync and new_source_model.supports_scheduled_sync:
                active_schemas.append(schema_model)

        try:
            for active_schema in active_schemas:
                sync_external_data_job_workflow(active_schema, create=True, should_sync=active_schema.should_sync)
        except Exception as e:
            # Log error but don't fail because the source model was already created
            logger.exception("Could not trigger external data job", exc_info=e)

        # Start CDC extraction schedule if any CDC schemas are active
        if cdc_enabled:
            try:
                from products.data_warehouse.backend.data_load.service import (
                    ensure_cdc_slot_cleanup_schedule,
                    sync_cdc_extraction_schedule,
                )

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

        return Response(status=status.HTTP_201_CREATED, data={"id": new_source_model.pk})

    def _setup_cdc_slot(
        self, source_impl, source_config, source_model: ExternalDataSource, payload: dict
    ) -> Response | None:
        """Set up CDC replication slot and publication on the source database.

        PostHog-managed: PostHog creates both the publication and the slot (requires
        table ownership on the source, plus REPLICATION).

        Self-managed: the customer's DBA creates the publication out-of-band; PostHog
        only verifies it exists and then creates the slot itself (publication creation
        requires table ownership, slot creation only requires REPLICATION — which the
        PostHog user must have either way to read the slot).

        Updates source_model.job_inputs with CDC config. Returns a Response on error,
        None on success.
        """
        from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import cdc_pg_connection

        management_mode = payload.get("cdc_management_mode", "posthog")
        slot_name = payload.get("cdc_slot_name") or f"posthog_{source_model.id.hex[:12]}"
        pub_name = payload.get("cdc_publication_name") or f"posthog_pub_{source_model.id.hex[:12]}"

        # Store CDC config in job_inputs
        job_inputs = source_model.job_inputs or {}
        job_inputs.update(
            {
                "cdc_enabled": True,
                "cdc_management_mode": management_mode,
                "cdc_slot_name": slot_name,
                "cdc_publication_name": pub_name,
                "cdc_auto_drop_slot": payload.get("cdc_auto_drop_slot", True),
                "cdc_lag_warning_threshold_mb": payload.get("cdc_lag_warning_threshold_mb", 1024),
                "cdc_lag_critical_threshold_mb": payload.get("cdc_lag_critical_threshold_mb", 10240),
            }
        )

        if management_mode == "posthog":
            from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import create_slot_and_publication

            try:
                with cdc_pg_connection(source_model) as conn:
                    consistent_point = create_slot_and_publication(
                        conn, slot_name, pub_name, source_config.schema, tables=[]
                    )
                    job_inputs["cdc_consistent_point"] = consistent_point
            except Exception as e:
                source_model.delete()
                logger.exception("Failed to create CDC slot and publication", error=str(e))
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": f"Failed to create replication slot: {e}",
                        "detail": str(e),
                    },
                )

        elif management_mode == "self_managed":
            from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import create_slot, publication_exists

            try:
                with cdc_pg_connection(source_model) as conn:
                    if not publication_exists(conn, pub_name):
                        source_model.delete()
                        return Response(
                            status=status.HTTP_400_BAD_REQUEST,
                            data={
                                "message": (
                                    f"Publication '{pub_name}' does not exist. Run the CREATE PUBLICATION "
                                    f"statement we showed you, then retry."
                                )
                            },
                        )
                    consistent_point = create_slot(conn, slot_name)
                    job_inputs["cdc_consistent_point"] = consistent_point
            except Exception as e:
                source_model.delete()
                logger.exception("Failed to set up self-managed CDC slot", error=str(e))
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": f"Failed to create replication slot: {e}"},
                )

        source_model.job_inputs = job_inputs
        source_model.save(update_fields=["job_inputs", "updated_at"])
        return None

    def _add_table_to_cdc_publication(
        self, source_model: ExternalDataSource, pub_name: str, db_schema: str, table_name: str
    ) -> None:
        """Best-effort add a table to the CDC publication during source creation."""
        from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import (
            add_table_to_publication,
            cdc_pg_connection,
        )

        try:
            with cdc_pg_connection(source_model) as conn:
                add_table_to_publication(conn, pub_name, db_schema, table_name)
        except Exception as e:
            logger.exception(
                "Failed to add table to CDC publication",
                table=table_name,
                pub_name=pub_name,
                error=str(e),
            )

    def prefix_required(self, source_type: str) -> bool:
        source_type_exists = (
            ExternalDataSource.objects.exclude(deleted=True)
            .filter(team_id=self.team.pk, source_type=source_type)
            .exists()
        )
        return source_type_exists

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
                schema.soft_delete()

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

        for schema in schemas:
            try:
                delete_external_data_schedule(str(schema.id))
            except Exception as e:
                capture_exception(e)

            try:
                schema.delete_table()
            except Exception as e:
                capture_exception(e)

        try:
            delete_external_data_schedule(str(instance.id))
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
            200: {"type": "object", "properties": {"added": {"type": "integer"}, "deleted": {"type": "integer"}}}
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
        try:
            source_type = ExternalDataSourceType(instance.source_type)
            source = SourceRegistry.get_source(source_type)
            config = source.parse_config(instance.job_inputs)
            schemas = source.get_schemas(config, self.team_id)
            connection_metadata = (
                get_direct_postgres_connection_metadata(
                    source_impl=source,
                    source_config=config,
                    team_id=self.team_id,
                    source_model=instance,
                    fallback=instance.connection_metadata,
                )
                if instance.is_direct_postgres
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
            logger.exception("Could not fetch schemas from source", exc_info=e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Could not fetch schemas from source."},
            )
        descriptions = {s.name: s.description for s in schemas}
        with transaction.atomic():
            ExternalDataSource._base_manager.filter(pk=instance.pk).select_for_update().get()
            if instance.is_direct_postgres and connection_metadata != instance.connection_metadata:
                instance.connection_metadata = connection_metadata
                instance.save(update_fields=["connection_metadata", "updated_at"])
            schemas_created, schemas_deleted = sync_old_schemas_with_new_schemas(
                schema_names,
                source_id=str(instance.id),
                team_id=self.team_id,
                descriptions=descriptions,
            )

            if instance.is_direct_postgres:
                reconciled_deleted_schemas = reconcile_direct_postgres_schemas(
                    source=instance,
                    source_schemas=schemas,
                    team_id=self.team_id,
                )
                if reconciled_deleted_schemas:
                    schemas_deleted = list({*schemas_deleted, *reconciled_deleted_schemas})
        logger.debug(
            "refresh_schemas completed",
            source_id=str(instance.id),
            team_id=self.team_id,
            added=len(schemas_created),
            deleted=len(schemas_deleted),
        )
        return Response(
            status=status.HTTP_200_OK,
            data={"added": len(schemas_created), "deleted": len(schemas_deleted)},
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

        source_type_model = ExternalDataSourceType(source_type)
        source = SourceRegistry.get_source(source_type_model)
        is_valid, errors = source.validate_config(request.data)
        if not is_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid source config: {', '.join(errors)}"},
            )
        source_config: Config = source.parse_config(request.data)

        access_method = request.data.get("access_method", ExternalDataSource.AccessMethod.WAREHOUSE)
        if source_type_model == ExternalDataSourceType.POSTGRES and isinstance(source, PostgresSource):
            credentials_valid, credentials_error = source.validate_credentials_for_access_method(
                cast(Any, source_config), self.team_id, access_method
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
        except Exception as e:
            capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": str(e)},
            )

        data = [
            {
                "table": schema.name,
                "should_sync": False,
                "incremental_fields": schema.incremental_fields,
                "incremental_available": schema.supports_incremental,
                "append_available": schema.supports_append,
                "cdc_available": schema.supports_cdc if is_cdc_enabled_for_team(self.team) else None,
                "incremental_field": schema.incremental_fields[0]["field"]
                if len(schema.incremental_fields) > 0 and len(schema.incremental_fields[0]["field"]) > 0
                else None,
                "sync_type": None,
                "rows": schema.row_count,
                "supports_webhooks": schema.supports_webhooks,
                "description": schema.description,
                "should_sync_default": schema.should_sync_default,
                "available_columns": [
                    {"field": col_name, "label": col_name, "type": col_type, "nullable": nullable}
                    for col_name, col_type, nullable in schema.columns
                ],
                "detected_primary_keys": schema.detected_primary_keys,
            }
            for schema in schemas
        ]
        return Response(status=status.HTTP_200_OK, data=data)

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
        if source_type != ExternalDataSourceType.POSTGRES:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "CDC prerequisite checks are only supported for Postgres."},
            )

        from posthog.temporal.data_imports.sources.postgres.source import PostgresSource

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

    @action(methods=["POST"], detail=False)
    def source_prefix(self, request: Request, *arg: Any, **kwargs: Any):
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]
        access_method = request.data.get("access_method", ExternalDataSource.AccessMethod.WAREHOUSE)

        if access_method == ExternalDataSource.AccessMethod.DIRECT:
            if source_type != ExternalDataSourceType.POSTGRES:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Direct query mode is currently supported only for Postgres sources."},
                )

            normalized_prefix = prefix.strip() if isinstance(prefix, str) else ""
            if not normalized_prefix:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Name is required for direct query sources"},
                )

            return Response(status=status.HTTP_200_OK)

        if self.prefix_required(source_type):
            if not prefix:
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

    @action(methods=["GET"], detail=False)
    def wizard(self, request: Request, *arg: Any, **kwargs: Any):
        sources = SourceRegistry.get_all_sources()
        configs = {name: source.get_source_config for name, source in sources.items()}

        return Response(
            status=status.HTTP_200_OK,
            data={str(key): value.model_dump() for key, value in configs.items()},
        )

    @extend_schema(responses=ExternalDataSourceConnectionOptionSerializer(many=True))
    @action(methods=["GET"], detail=False)
    def connections(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = (
            ExternalDataSource._base_manager.filter(
                team_id=self.team_id,
                access_method=ExternalDataSource.AccessMethod.DIRECT,
                source_type=ExternalDataSourceType.POSTGRES,
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

        if instance.job_inputs:
            try:
                config = source.parse_config(instance.job_inputs)
                external_status = source.get_external_webhook_info(config, webhook_url, self.team_id)
            except Exception as e:
                capture_exception(e)

        schema_mapping = {}
        if hog_function.inputs:
            schema_mapping = hog_function.inputs.get("schema_mapping", {}).get("value", {})

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
                "external_status": dataclasses.asdict(external_status) if external_status else None,
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
            },
        )

    @action(methods=["POST"], detail=True)
    def update_webhook_inputs(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()

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

        required_fields = [f.name for f in webhook_fields if hasattr(f, "required") and f.required]
        missing_fields = [name for name in required_fields if not inputs.get(name)]
        if missing_fields:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Missing required fields: {', '.join(missing_fields)}"},
            )

        schema_ids = list(
            ExternalDataSchema.objects.filter(
                source=instance,
                team_id=self.team_id,
                sync_type=ExternalDataSchema.SyncType.WEBHOOK,
                should_sync=True,
            )
            .exclude(deleted=True)
            .values_list("id", flat=True)
        )

        if not schema_ids:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "No eligible schemas found"},
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

        assert hog_function.inputs is not None
        hog_function.inputs = {
            **hog_function.inputs,
            **{key: {"value": value} for key, value in inputs.items()},
        }
        hog_function.save(update_fields=["inputs", "encrypted_inputs"])

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
        post_commit_actions: list[Callable[[], None]] = []
        update_serializer_context = {**serializer_context, "post_commit_actions": post_commit_actions}

        with transaction.atomic():
            for schema_update in schema_updates:
                schema_id = schema_update["id"]
                schema = source_schemas_by_id[schema_id]
                schema_payload = {key: value for key, value in schema_update.items() if key != "id"}

                schema_serializer = ExternalDataSchemaSerializer(
                    schema,
                    data=schema_payload,
                    partial=True,
                    context=update_serializer_context,
                )
                schema_serializer.is_valid(raise_exception=True)
                updated_schemas.append(schema_serializer.save())

        for post_commit_action in post_commit_actions:
            post_commit_action()

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


@dataclasses.dataclass(frozen=True)
class ExternalDataSourceContext(ActivityContextBase):
    source_type: str
    prefix: str | None
    description: str | None
    created_by_user_id: str | None
    created_by_user_email: str | None
    created_by_user_name: str | None


@mutable_receiver(model_activity_signal, sender=ExternalDataSource)
def handle_external_data_source_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    # Use after_update for create/update, before_update for delete
    external_data_source = after_update or before_update

    if not external_data_source:
        return

    created_by_user_id, created_by_user_email, created_by_user_name = get_external_data_source_created_by_info(
        external_data_source
    )
    detail_name = get_external_data_source_detail_name(external_data_source)

    context = ExternalDataSourceContext(
        source_type=external_data_source.source_type or "",
        prefix=external_data_source.prefix,
        description=external_data_source.description,
        created_by_user_id=created_by_user_id,
        created_by_user_email=created_by_user_email,
        created_by_user_name=created_by_user_name,
    )

    log_activity(
        organization_id=external_data_source.team.organization_id,
        team_id=external_data_source.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=external_data_source.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=detail_name,
            context=context,
        ),
    )
