import re
import uuid
from typing import Any

import structlog
import temporalio
from dateutil import parser
from django.db.models import Prefetch, Q
from psycopg2 import OperationalError
from rest_framework import filters, serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from snowflake.connector.errors import DatabaseError, ForbiddenError, ProgrammingError
from sshtunnel import BaseSSHTunnelForwarderError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.cloud_utils import is_cloud
from posthog.exceptions_capture import capture_exception
from posthog.hogql.database.database import create_hogql_database
from posthog.models.user import User
from posthog.temporal.data_imports.pipelines.bigquery import (
    BigQuerySourceConfig,
    filter_incremental_fields as filter_bigquery_incremental_fields,
    get_schemas as get_bigquery_schemas,
    validate_credentials as validate_bigquery_credentials,
)
from posthog.temporal.data_imports.pipelines.chargebee import (
    validate_credentials as validate_chargebee_credentials,
)
from posthog.temporal.data_imports.pipelines.doit.source import (
    DOIT_INCREMENTAL_FIELDS,
    DoItSourceConfig,
    doit_list_reports,
)
from posthog.temporal.data_imports.pipelines.google_ads import (
    GoogleAdsOAuthSourceConfig,
    get_incremental_fields as get_google_ads_incremental_fields,
    get_schemas as get_google_ads_schemas,
)
from posthog.temporal.data_imports.pipelines.google_sheets.source import (
    GoogleSheetsServiceAccountSourceConfig,
    get_schemas as get_google_sheets_schemas,
    get_schema_incremental_fields as get_google_sheets_schema_incremental_fields,
)
from posthog.temporal.data_imports.pipelines.schemas import (
    PIPELINE_TYPE_INCREMENTAL_ENDPOINTS_MAPPING,
    PIPELINE_TYPE_INCREMENTAL_FIELDS_MAPPING,
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from posthog.temporal.data_imports.pipelines.snowflake import (
    SnowflakeSourceConfig,
    get_schemas as get_snowflake_schemas,
)
from posthog.temporal.data_imports.pipelines.stripe import (
    StripePermissionError,
    validate_credentials as validate_stripe_credentials,
)
from posthog.temporal.data_imports.pipelines.vitally import (
    validate_credentials as validate_vitally_credentials,
)
from posthog.temporal.data_imports.pipelines.zendesk import (
    validate_credentials as validate_zendesk_credentials,
)
from posthog.utils import get_instance_region, str_to_bool
from posthog.warehouse.api.available_sources import AVAILABLE_SOURCES
from posthog.warehouse.api.external_data_schema import (
    ExternalDataSchemaSerializer,
    SimpleExternalDataSchemaSerializer,
)
from posthog.warehouse.data_load.service import (
    cancel_external_data_workflow,
    delete_data_import_folder,
    delete_external_data_schedule,
    is_any_external_data_schema_paused,
    sync_external_data_job_workflow,
    trigger_external_data_source_workflow,
)
from posthog.warehouse.models import (
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)
from posthog.warehouse.models.external_data_schema import (
    filter_mssql_incremental_fields,
    filter_mysql_incremental_fields,
    filter_postgres_incremental_fields,
    filter_snowflake_incremental_fields,
    get_postgres_row_count,
    get_sql_schemas_for_source_type,
)
from posthog.temporal.data_imports.pipelines.mongo import (
    MongoSourceConfig,
    get_schemas as get_mongo_schemas,
    filter_mongo_incremental_fields,
)
from posthog.warehouse.models.ssh_tunnel import SSHTunnel

logger = structlog.get_logger(__name__)


def get_generic_sql_error(source_type: ExternalDataSource.Type):
    if source_type == ExternalDataSource.Type.MYSQL:
        name = "MySQL"
    elif source_type == ExternalDataSource.Type.MSSQL:
        name = "SQL database"
    else:
        name = "Postgres"

    return f"Could not connect to {name}. Please check all connection details are valid."


GenericSnowflakeError = "Could not connect to Snowflake. Please check all connection details are valid."
PostgresErrors = {
    "password authentication failed for user": "Invalid user or password",
    "could not translate host name": "Could not connect to the host",
    "Is the server running on that host and accepting TCP/IP connections": "Could not connect to the host on the port given",
    'database "': "Database does not exist",
    "timeout expired": "Connection timed out. Does your database have our IP addresses allowed?",
}
SnowflakeErrors = {
    "No active warehouse selected in the current session": "No warehouse found for selected role",
    "or attempt to login with another role": "Role specified doesn't exist or is not authorized",
    "Incorrect username or password was specified": "Incorrect username or password was specified",
    "This session does not have a current database": "Database specified not found",
    "Verify the account name is correct": "Can't find an account with the specified account ID",
}
MSSQLErrors = {
    "Login failed for user": "Login failed for database",
    "Adaptive Server is unavailable or does not exist": "Could not connect to SQL server - check server host and port",
    "connection timed out": "Could not connect to SQL server - check server firewall settings",
}


class ExternalDataJobSerializers(serializers.ModelSerializer):
    schema = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ExternalDataJob
        fields = [
            "id",
            "created_at",
            "created_by",
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


class ExternalDataSourceSerializers(serializers.ModelSerializer):
    account_id = serializers.CharField(write_only=True)
    client_secret = serializers.CharField(write_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)
    created_by = serializers.SerializerMethodField(read_only=True)
    latest_error = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    schemas = serializers.SerializerMethodField(read_only=True)
    revenue_analytics_enabled = serializers.BooleanField(default=False)

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
            "revenue_analytics_enabled",
            "last_run_at",
            "schemas",
            "job_inputs",
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
            "prefix",
        ]

    """
    This method is used to remove sensitive fields from the response.
    IMPORTANT: This method should be updated when a new source type is added to allow for editing of the new source.
    """

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        # non-sensitive fields
        whitelisted_keys = {
            # stripe
            "stripe_account_id",
            # sql
            "database",
            "host",
            "port",
            "user",
            "schema",
            "ssh-tunnel",
            "using_ssl",
            # vitally
            "payload",
            "prefix",
            "regionsubdomain",
            "source_type",
            # chargebee
            "site_name",
            # zendesk
            "subdomain",
            "email_address",
            # hubspot
            "redirect_uri",
            # snowflake
            "account_id",
            "warehouse",
            "role",
            # bigquery
            "dataset_id",
            "project_id",
            "client_email",
            "token_uri",
            "temporary-dataset",
        }
        job_inputs = representation.get("job_inputs", {})
        if isinstance(job_inputs, dict):
            # Reconstruct ssh-tunnel (if needed) structure for UI handling
            if "ssh_tunnel_enabled" in job_inputs:
                ssh_tunnel = {
                    "enabled": job_inputs.pop("ssh_tunnel_enabled", False),
                    "host": job_inputs.pop("ssh_tunnel_host", None),
                    "port": job_inputs.pop("ssh_tunnel_port", None),
                    "auth_type": {
                        "selection": job_inputs.pop("ssh_tunnel_auth_type", None),
                        "username": job_inputs.pop("ssh_tunnel_auth_type_username", None),
                        "password": None,
                        "passphrase": None,
                        "private_key": None,
                    },
                }
                job_inputs["ssh-tunnel"] = ssh_tunnel

            # Reconstruct BigQuery structure for UI handling
            if job_inputs.get("using_temporary_dataset") == "True":  # encrypted as string
                job_inputs["temporary-dataset"] = {
                    "enabled": True,
                    "temporary_dataset_id": job_inputs.pop("temporary_dataset_id", None),
                }

            # Remove sensitive fields
            for key in list(job_inputs.keys()):  # Use list() to avoid modifying dict during iteration
                if key not in whitelisted_keys:
                    job_inputs.pop(key, None)

        return representation

    def get_last_run_at(self, instance: ExternalDataSource) -> str:
        latest_completed_run = instance.ordered_jobs[0] if instance.ordered_jobs else None  # type: ignore

        return latest_completed_run.created_at if latest_completed_run else None

    def get_created_by(self, instance: ExternalDataSource) -> str | None:
        return instance.created_by.email if instance.created_by else None

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

    def get_latest_error(self, instance: ExternalDataSource):
        schema_with_error = instance.schemas.filter(latest_error__isnull=False).first()
        return schema_with_error.latest_error if schema_with_error else None

    def get_schemas(self, instance: ExternalDataSource):
        return ExternalDataSchemaSerializer(instance.schemas, many=True, read_only=True, context=self.context).data

    def update(self, instance: ExternalDataSource, validated_data: Any) -> Any:
        """Update source ensuring we merge with existing job inputs to allow partial updates."""
        existing_job_inputs = instance.job_inputs

        new_job_inputs = validated_data.get("job_inputs", {})
        self._normalize_ssh_tunnel_structure(new_job_inputs)

        if instance.source_type == ExternalDataSource.Type.SNOWFLAKE:
            new_job_inputs = parse_snowflake_job_inputs(new_job_inputs)

        elif instance.source_type == ExternalDataSource.Type.ZENDESK:
            # Zendesk source requires a `zendesk_*` prefix, but our frontend displays
            # values without a prefix.
            # TODO: Integrate configuration class here.
            new_job_inputs = {f"zendesk_{k}": v for k, v in new_job_inputs.items()}

        elif instance.source_type == ExternalDataSource.Type.BIGQUERY:
            new_job_inputs = parse_bigquery_job_inputs(new_job_inputs)

        if existing_job_inputs:
            validated_data["job_inputs"] = {**existing_job_inputs, **new_job_inputs}

        updated_source: ExternalDataSource = super().update(instance, validated_data)

        return updated_source

    def _normalize_ssh_tunnel_structure(self, job_inputs: dict) -> dict:
        """Convert nested SSH tunnel structure to flat keys."""
        if "ssh-tunnel" in job_inputs:
            ssh_tunnel = job_inputs.pop("ssh-tunnel", {})  # Remove the nested structure after extracting
            if ssh_tunnel:
                job_inputs["ssh_tunnel_enabled"] = ssh_tunnel.get("enabled")
                job_inputs["ssh_tunnel_host"] = ssh_tunnel.get("host")
                job_inputs["ssh_tunnel_port"] = ssh_tunnel.get("port")

                auth_type = ssh_tunnel.get("auth_type", {})
                if auth_type:
                    job_inputs["ssh_tunnel_auth_type"] = auth_type.get("selection")
                    job_inputs["ssh_tunnel_auth_type_username"] = auth_type.get("username")
                    job_inputs["ssh_tunnel_auth_type_password"] = auth_type.get("password")
                    job_inputs["ssh_tunnel_auth_type_passphrase"] = auth_type.get("passphrase")
                    job_inputs["ssh_tunnel_auth_type_private_key"] = auth_type.get("private_key")
        return job_inputs


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


class ExternalDataSourceViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete External data Sources.
    """

    scope_object = "INTERNAL"
    queryset = ExternalDataSource.objects.all()
    serializer_class = ExternalDataSourceSerializers
    filter_backends = [filters.SearchFilter]
    search_fields = ["source_id"]
    ordering = "-created_at"

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["database"] = create_hogql_database(team_id=self.team_id)

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

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        if self.prefix_required(source_type):
            if not prefix:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Source type already exists. Prefix is required"},
                )
            elif self.prefix_exists(source_type, prefix):
                return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Prefix already exists"})

        if is_any_external_data_schema_paused(self.team_id):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please increase your billing limit to resume syncing."},
            )

        # Strip leading and trailing whitespace
        payload = request.data["payload"]
        if payload is not None:
            for key, value in payload.items():
                if isinstance(value, str):
                    payload[key] = value.strip()

        # TODO: remove dummy vars
        if source_type == ExternalDataSource.Type.STRIPE:
            new_source_model = self._handle_stripe_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.HUBSPOT:
            new_source_model = self._handle_hubspot_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.ZENDESK:
            new_source_model = self._handle_zendesk_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.SALESFORCE:
            new_source_model = self._handle_salesforce_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.VITALLY:
            new_source_model = self._handle_vitally_source(request, *args, **kwargs)
        elif source_type in [
            ExternalDataSource.Type.POSTGRES,
            ExternalDataSource.Type.MYSQL,
            ExternalDataSource.Type.MSSQL,
        ]:
            try:
                new_source_model, sql_schemas = self._handle_sql_source(request, *args, **kwargs)
            except InternalPostgresError:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST, data={"message": "Cannot use internal Postgres database"}
                )
            except Exception:
                raise
        elif source_type == ExternalDataSource.Type.SNOWFLAKE:
            new_source_model, snowflake_schemas = self._handle_snowflake_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.BIGQUERY:
            new_source_model, bigquery_schemas = self._handle_bigquery_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.CHARGEBEE:
            new_source_model = self._handle_chargebee_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.GOOGLEADS:
            new_source_model, google_ads_schemas = self._handle_google_ads_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.TEMPORALIO:
            new_source_model = self._handle_temporalio_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.DOIT:
            new_source_model, doit_schemas = self._handle_doit_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.MONGODB:
            new_source_model, mongo_schemas = self._handle_mongo_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.GOOGLESHEETS:
            new_source_model, google_sheets_schemas = self._handle_google_sheets_source(request, *args, **kwargs)
        else:
            raise NotImplementedError(f"Source type {source_type} not implemented")

        payload = request.data["payload"]
        schemas = payload.get("schemas", None)
        if source_type in [
            ExternalDataSource.Type.POSTGRES,
            ExternalDataSource.Type.MYSQL,
            ExternalDataSource.Type.MSSQL,
        ]:
            default_schemas = sql_schemas
        elif source_type == ExternalDataSource.Type.MONGODB:
            default_schemas = mongo_schemas
        elif source_type == ExternalDataSource.Type.SNOWFLAKE:
            default_schemas = snowflake_schemas
        elif source_type == ExternalDataSource.Type.BIGQUERY:
            default_schemas = bigquery_schemas
        elif source_type == ExternalDataSource.Type.GOOGLEADS:
            default_schemas = google_ads_schemas
        elif source_type == ExternalDataSource.Type.DOIT:
            default_schemas = doit_schemas
        elif source_type == ExternalDataSource.Type.GOOGLESHEETS:
            default_schemas = google_sheets_schemas
        else:
            default_schemas = list(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[source_type])

        if not schemas or not isinstance(schemas, list):
            new_source_model.delete()
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Schemas not given"},
            )

        # Return 400 if we get any schema names that don't exist in our source
        if any(schema.get("name") not in default_schemas for schema in schemas):
            new_source_model.delete()
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Schemas given do not exist in source"},
            )

        active_schemas: list[ExternalDataSchema] = []

        for schema in schemas:
            sync_type = schema.get("sync_type")
            requires_incremental_fields = sync_type == "incremental" or sync_type == "append"
            incremental_field = schema.get("incremental_field")
            incremental_field_type = schema.get("incremental_field_type")
            sync_time_of_day = schema.get("sync_time_of_day")

            if requires_incremental_fields and incremental_field is None:
                new_source_model.delete()
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Incremental schemas given do not have an incremental field set"},
                )

            if requires_incremental_fields and incremental_field_type is None:
                new_source_model.delete()
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Incremental schemas given do not have an incremental field type set"},
                )

            schema_model = ExternalDataSchema.objects.create(
                name=schema.get("name"),
                team=self.team,
                source=new_source_model,
                should_sync=schema.get("should_sync"),
                sync_type=sync_type,
                sync_time_of_day=sync_time_of_day,
                sync_type_config=(
                    {
                        "incremental_field": incremental_field,
                        "incremental_field_type": incremental_field_type,
                    }
                    if requires_incremental_fields
                    else {}
                ),
            )

            if schema.get("should_sync"):
                active_schemas.append(schema_model)

        try:
            for active_schema in active_schemas:
                sync_external_data_job_workflow(active_schema, create=True, should_sync=active_schema.should_sync)
        except Exception as e:
            # Log error but don't fail because the source model was already created
            logger.exception("Could not trigger external data job", exc_info=e)

        return Response(status=status.HTTP_201_CREATED, data={"id": new_source_model.pk})

    def _handle_stripe_source(self, request: Request, *args: Any, **kwargs: Any) -> ExternalDataSource:
        payload = request.data["payload"]
        client_secret = payload.get("stripe_secret_key")
        account_id = payload.get("stripe_account_id", None)
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]
        # TODO: remove dummy vars
        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            created_by=request.user if isinstance(request.user, User) else None,
            team=self.team,
            status="Running",
            source_type=source_type,
            revenue_analytics_enabled=True,
            job_inputs={"stripe_secret_key": client_secret, "stripe_account_id": account_id},
            prefix=prefix,
        )

        return new_source_model

    def _handle_vitally_source(self, request: Request, *args: Any, **kwargs: Any) -> ExternalDataSource:
        payload = request.data["payload"]
        secret_token = payload.get("secret_token")

        region_obj = payload.get("region", {})
        region = region_obj.get("selection")
        subdomain = region_obj.get("subdomain", None)

        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        # TODO: remove dummy vars
        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            created_by=request.user if isinstance(request.user, User) else None,
            team=self.team,
            status="Running",
            source_type=source_type,
            job_inputs={"secret_token": secret_token, "region": region, "subdomain": subdomain},
            prefix=prefix,
        )

        return new_source_model

    def _handle_chargebee_source(self, request: Request, *args: Any, **kwargs: Any) -> ExternalDataSource:
        payload = request.data["payload"]
        api_key = payload.get("api_key")
        site_name = payload.get("site_name")
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            created_by=request.user if isinstance(request.user, User) else None,
            status="Running",
            source_type=source_type,
            job_inputs={"api_key": api_key, "site_name": site_name},
            prefix=prefix,
        )

        return new_source_model

    def _handle_temporalio_source(self, request: Request, *args: Any, **kwargs: Any) -> ExternalDataSource:
        payload = request.data["payload"]
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        host = payload.get("host", "")
        port = payload.get("port", "")
        namespace = payload.get("namespace", "")
        encryption_key = payload.get("encryption_key", None)
        server_client_root_ca = payload.get("server_client_root_ca", "")
        client_certificate = payload.get("client_certificate", "")
        client_private_key = payload.get("client_private_key", "")

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            created_by=request.user if isinstance(request.user, User) else None,
            status="Running",
            source_type=source_type,
            job_inputs={
                "host": host,
                "port": port,
                "namespace": namespace,
                "encryption_key": encryption_key,
                "server_client_root_ca": server_client_root_ca,
                "client_certificate": client_certificate,
                "client_private_key": client_private_key,
            },
            prefix=prefix,
        )

        return new_source_model

    def _handle_doit_source(self, request: Request, *args: Any, **kwargs: Any) -> tuple[ExternalDataSource, list[Any]]:
        payload = request.data["payload"]
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        api_key = payload.get("api_key", "")

        if len(api_key) == 0:
            raise Exception("Missing api_key")

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            created_by=request.user if isinstance(request.user, User) else None,
            status="Running",
            source_type=source_type,
            job_inputs={
                "api_key": api_key,
            },
            prefix=prefix,
        )

        reports = doit_list_reports(DoItSourceConfig(api_key=api_key))

        return new_source_model, [name for name, _ in reports]

    def _handle_google_sheets_source(
        self, request: Request, *args: Any, **kwargs: Any
    ) -> tuple[ExternalDataSource, list[Any]]:
        payload = request.data["payload"]
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        spreadsheet_url = payload.get("spreadsheet_url", "")

        if len(spreadsheet_url) == 0:
            raise Exception("Missing spreadsheet_url")

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            created_by=request.user if isinstance(request.user, User) else None,
            status="Running",
            source_type=source_type,
            job_inputs={
                "spreadsheet_url": spreadsheet_url,
            },
            prefix=prefix,
        )

        schemas = get_google_sheets_schemas(GoogleSheetsServiceAccountSourceConfig(spreadsheet_url=spreadsheet_url))

        return new_source_model, [name for name, _ in schemas]

    def _handle_zendesk_source(self, request: Request, *args: Any, **kwargs: Any) -> ExternalDataSource:
        payload = request.data["payload"]
        api_key = payload.get("api_key")
        subdomain = payload.get("subdomain")
        email_address = payload.get("email_address")
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        # TODO: remove dummy vars
        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            created_by=request.user if isinstance(request.user, User) else None,
            status="Running",
            source_type=source_type,
            job_inputs={
                "zendesk_login_method": "api_key",  # We should support the Zendesk OAuth flow in the future, and so with this we can do backwards compatibility
                "zendesk_api_key": api_key,
                "zendesk_subdomain": subdomain,
                "zendesk_email_address": email_address,
            },
            prefix=prefix,
        )

        return new_source_model

    def _handle_salesforce_source(self, request: Request, *args: Any, **kwargs: Any) -> ExternalDataSource:
        payload = request.data["payload"]
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]
        salesforce_integration_id = payload.get("salesforce_integration_id")

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            created_by=request.user if isinstance(request.user, User) else None,
            status="Running",
            source_type=source_type,
            job_inputs={
                "salesforce_integration_id": salesforce_integration_id,
            },
            prefix=prefix,
        )

        return new_source_model

    def _handle_hubspot_source(self, request: Request, *args: Any, **kwargs: Any) -> ExternalDataSource:
        payload = request.data["payload"]
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]
        hubspot_integration_id = payload.get("hubspot_integration_id")

        # TODO: remove dummy vars
        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            created_by=request.user if isinstance(request.user, User) else None,
            status="Running",
            source_type=source_type,
            job_inputs={
                "hubspot_integration_id": hubspot_integration_id,
            },
            prefix=prefix,
        )

        return new_source_model

    def _handle_sql_source(self, request: Request, *args: Any, **kwargs: Any) -> tuple[ExternalDataSource, list[Any]]:
        payload = request.data["payload"]
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        host = payload.get("host")
        port = payload.get("port")
        database = payload.get("database")

        user = payload.get("user")
        password = payload.get("password")
        schema = payload.get("schema")

        ssh_tunnel_obj = payload.get("ssh-tunnel", {})
        using_ssh_tunnel = ssh_tunnel_obj.get("enabled", False)
        ssh_tunnel_host = ssh_tunnel_obj.get("host", None)
        ssh_tunnel_port = ssh_tunnel_obj.get("port", None)
        ssh_tunnel_auth_type_obj = ssh_tunnel_obj.get("auth_type", {})
        ssh_tunnel_auth_type = ssh_tunnel_auth_type_obj.get("selection", None)
        ssh_tunnel_auth_type_username = ssh_tunnel_auth_type_obj.get("username", None)
        ssh_tunnel_auth_type_password = ssh_tunnel_auth_type_obj.get("password", None)
        ssh_tunnel_auth_type_passphrase = ssh_tunnel_auth_type_obj.get("passphrase", None)
        ssh_tunnel_auth_type_private_key = ssh_tunnel_auth_type_obj.get("private_key", None)

        using_ssl_str = payload.get("using_ssl", "1")
        using_ssl = str_to_bool(using_ssl_str)

        if not self._validate_database_host(host, self.team_id, using_ssh_tunnel):
            raise InternalPostgresError()

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            created_by=request.user if isinstance(request.user, User) else None,
            status="Running",
            source_type=source_type,
            job_inputs={
                "host": host,
                "port": port,
                "database": database,
                "user": user,
                "password": password,
                "schema": schema,
                "ssh_tunnel_enabled": using_ssh_tunnel,
                "ssh_tunnel_host": ssh_tunnel_host,
                "ssh_tunnel_port": ssh_tunnel_port,
                "ssh_tunnel_auth_type": ssh_tunnel_auth_type,
                "ssh_tunnel_auth_type_username": ssh_tunnel_auth_type_username,
                "ssh_tunnel_auth_type_password": ssh_tunnel_auth_type_password,
                "ssh_tunnel_auth_type_passphrase": ssh_tunnel_auth_type_passphrase,
                "ssh_tunnel_auth_type_private_key": ssh_tunnel_auth_type_private_key,
                "using_ssl": using_ssl,
            },
            prefix=prefix,
        )

        schemas = get_sql_schemas_for_source_type(source_type, new_source_model.job_inputs)

        return new_source_model, list(schemas.keys())

    def _handle_snowflake_source(
        self, request: Request, *args: Any, **kwargs: Any
    ) -> tuple[ExternalDataSource, list[Any]]:
        payload = request.data["payload"]
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        job_inputs = parse_snowflake_job_inputs(payload)

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            created_by=request.user if isinstance(request.user, User) else None,
            status="Running",
            source_type=source_type,
            job_inputs=job_inputs,
            prefix=prefix,
        )

        schemas = get_snowflake_schemas(SnowflakeSourceConfig.from_dict(new_source_model.job_inputs))

        return new_source_model, list(schemas.keys())

    def _handle_bigquery_source(
        self, request: Request, *args: Any, **kwargs: Any
    ) -> tuple[ExternalDataSource, list[Any]]:
        payload = request.data["payload"]
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        job_inputs = parse_bigquery_job_inputs(payload)

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            created_by=request.user if isinstance(request.user, User) else None,
            status="Running",
            source_type=source_type,
            job_inputs=job_inputs,
            prefix=prefix,
        )

        schemas = get_bigquery_schemas(BigQuerySourceConfig.from_dict(new_source_model.job_inputs))

        return new_source_model, list(schemas.keys())

    def _handle_google_ads_source(
        self, request: Request, *args: Any, **kwargs: Any
    ) -> tuple[ExternalDataSource, list[Any]]:
        payload = request.data["payload"]
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        customer_id = payload.get("customer_id", "")
        google_ads_integration_id = payload.get("google_ads_integration_id")

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            created_by=request.user if isinstance(request.user, User) else None,
            status="Running",
            source_type=source_type,
            job_inputs={"customer_id": customer_id, "google_ads_integration_id": google_ads_integration_id},
            prefix=prefix,
        )

        config = GoogleAdsOAuthSourceConfig.from_dict({**new_source_model.job_inputs, **{"resource_name": ""}})
        schemas = get_google_ads_schemas(config, self.team_id)

        return new_source_model, list(schemas.keys())

    def _handle_mongo_source(self, request: Request, *args: Any, **kwargs: Any) -> tuple[ExternalDataSource, list[Any]]:
        payload = request.data["payload"]
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        connection_string = payload.get("connection_string")

        if not connection_string:
            raise Exception("Missing required parameter: connection_string")

        # Parse connection string to validate and extract database for host validation
        try:
            from posthog.temporal.data_imports.pipelines.mongo.mongo import _parse_connection_string

            connection_params = _parse_connection_string(connection_string)
        except Exception:
            raise Exception(f"Invalid connection string")

        if not connection_params.get("database"):
            raise Exception("Database name is required in connection string")

        # Validate database host
        if not self._validate_mongo_host(connection_params):
            raise Exception("Cannot use internal database")

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            created_by=request.user if isinstance(request.user, User) else None,
            status="Running",
            source_type=source_type,
            job_inputs={
                "connection_string": connection_string,
            },
            prefix=prefix,
        )

        schemas = get_mongo_schemas(MongoSourceConfig.from_dict(new_source_model.job_inputs))

        return new_source_model, list(schemas.keys())

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

        latest_running_job = (
            ExternalDataJob.objects.filter(pipeline_id=instance.pk, team_id=instance.team_id)
            .order_by("-created_at")
            .first()
        )
        if latest_running_job and latest_running_job.workflow_id and latest_running_job.status == "Running":
            cancel_external_data_workflow(latest_running_job.workflow_id)

        for schema in (
            ExternalDataSchema.objects.exclude(deleted=True)
            .filter(team_id=self.team_id, source_id=instance.id, should_sync=True)
            .all()
        ):
            try:
                delete_data_import_folder(schema.folder_path())
            except Exception as e:
                logger.exception(f"Could not clean up data import folder: {schema.folder_path()}", exc_info=e)
                pass
            delete_external_data_schedule(str(schema.id))

        delete_external_data_schedule(str(instance.id))

        for schema in instance.schemas.all():
            if schema.table:
                schema.table.soft_delete()
            schema.soft_delete()
        instance.soft_delete()

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["POST"], detail=True)
    def reload(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSource = self.get_object()

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

    @action(methods=["POST"], detail=False)
    def database_schema(self, request: Request, *arg: Any, **kwargs: Any):
        source_type = request.data.get("source_type", None)

        if source_type is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Missing required parameter: source_type"},
            )

        # Validate sourced credentials
        if source_type == ExternalDataSource.Type.STRIPE:
            key = request.data.get("stripe_secret_key", "")
            try:
                validate_stripe_credentials(api_key=key)
            except StripePermissionError as e:
                missing_resources = ", ".join(e.missing_permissions.keys())
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": f"Invalid credentials: Stripe API key lacks permissions for {missing_resources}"},
                )
            except Exception:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Invalid credentials: Stripe secret is incorrect"},
                )
        elif source_type == ExternalDataSource.Type.ZENDESK:
            subdomain = request.data.get("subdomain", "")
            api_key = request.data.get("api_key", "")
            email_address = request.data.get("email_address", "")

            subdomain_regex = re.compile("^[a-zA-Z0-9-]+$")
            if not subdomain_regex.match(subdomain):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Invalid credentials: Zendesk subdomain is incorrect"},
                )

            if not validate_zendesk_credentials(subdomain=subdomain, api_key=api_key, email_address=email_address):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Invalid credentials: Zendesk credentials are incorrect"},
                )
        elif source_type == ExternalDataSource.Type.VITALLY:
            secret_token = request.data.get("secret_token", "")
            region_obj = request.data.get("region", {})
            region = region_obj.get("selection", "")
            subdomain = region_obj.get("subdomain", "")

            subdomain_regex = re.compile("^[a-zA-Z-]+$")
            if region == "US" and not subdomain_regex.match(subdomain):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Invalid credentials: Vitally subdomain is incorrect"},
                )

            if not validate_vitally_credentials(subdomain=subdomain, secret_token=secret_token, region=region):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Invalid credentials: Vitally credentials are incorrect"},
                )
        elif source_type == ExternalDataSource.Type.BIGQUERY:
            dataset_id = request.data.get("dataset_id", "")
            key_file = request.data.get("key_file", {})

            dataset_project = request.data.get("dataset_project", {})
            dataset_project_id = dataset_project.get("dataset_project_id", None)

            if not validate_bigquery_credentials(
                dataset_id=dataset_id, key_file=key_file, dataset_project_id=dataset_project_id
            ):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Invalid credentials: BigQuery credentials are incorrect"},
                )

            bq_config = BigQuerySourceConfig.from_dict({"dataset_id": dataset_id, **key_file})

            bq_schemas = get_bigquery_schemas(
                bq_config,
                logger=logger,
            )

            filtered_results = [
                (table_name, filter_bigquery_incremental_fields(columns)) for table_name, columns in bq_schemas.items()
            ]

            result_mapped_to_options = [
                {
                    "table": table_name,
                    "should_sync": False,
                    "incremental_fields": [
                        {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                        for column_name, column_type in columns
                    ],
                    "incremental_available": True,
                    "append_available": True,
                    "incremental_field": columns[0][0] if len(columns) > 0 and len(columns[0]) > 0 else None,
                    "sync_type": None,
                }
                for table_name, columns in filtered_results
            ]

            return Response(status=status.HTTP_200_OK, data=result_mapped_to_options)
        elif source_type == ExternalDataSource.Type.CHARGEBEE:
            api_key = request.data.get("api_key", "")
            site_name = request.data.get("site_name", "")

            # Chargebee uses the term 'site' but it is effectively the subdomain
            subdomain_regex = re.compile("^[a-zA-Z-]+$")
            if not subdomain_regex.match(site_name):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Invalid credentials: Chargebee site name is incorrect"},
                )

            if not validate_chargebee_credentials(api_key=api_key, site_name=site_name):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Invalid credentials: Chargebee credentials are incorrect"},
                )

        elif source_type == ExternalDataSource.Type.GOOGLEADS:
            customer_id = request.data.get("customer_id")
            resource_name = request.data.get("resource_name", "")
            google_ads_integration_id = request.data.get("google_ads_integration_id", "")

            if not customer_id:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Missing required input: 'customer_id'"},
                )

            google_ads_config = GoogleAdsOAuthSourceConfig(
                customer_id=customer_id,
                google_ads_integration_id=google_ads_integration_id,
                resource_name=resource_name,
            )

            google_ads_schemas = get_google_ads_schemas(
                google_ads_config,
                self.team_id,
            )

            ads_incremental_fields = get_google_ads_incremental_fields()

            result_mapped_to_options = [
                {
                    "table": name,
                    "should_sync": False,
                    "incremental_fields": [
                        {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                        for column_name, column_type in ads_incremental_fields.get(name, [])
                    ],
                    "incremental_available": True,
                    "append_available": True,
                    "incremental_field": ads_incremental_fields[name][0][0]
                    if len(ads_incremental_fields.get(name, [])) > 0
                    else None,
                    "sync_type": None,
                }
                for name, _ in google_ads_schemas.items()
            ]

            return Response(status=status.HTTP_200_OK, data=result_mapped_to_options)
        elif source_type == ExternalDataSource.Type.DOIT:
            api_key = request.data.get("api_key")

            if not api_key:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Missing required input: 'api_key'"},
                )

            doit_config = DoItSourceConfig(api_key=api_key)
            reports = doit_list_reports(doit_config)
            result_mapped_to_options = [
                {
                    "table": name,
                    "should_sync": False,
                    "incremental_fields": DOIT_INCREMENTAL_FIELDS,
                    "incremental_available": True,
                    "append_available": True,
                    "incremental_field": None,
                    "sync_type": None,
                }
                for name, _ in reports
            ]

            return Response(status=status.HTTP_200_OK, data=result_mapped_to_options)
        elif source_type == ExternalDataSource.Type.GOOGLESHEETS:
            spreadsheet_url = request.data.get("spreadsheet_url")

            if not spreadsheet_url:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Missing required input: 'spreadsheet_url'"},
                )

            google_sheets_config = GoogleSheetsServiceAccountSourceConfig(spreadsheet_url=spreadsheet_url)
            sheets = get_google_sheets_schemas(google_sheets_config)
            result_mapped_to_options = [
                {
                    "table": name,
                    "should_sync": False,
                    "incremental_fields": get_google_sheets_schema_incremental_fields(google_sheets_config, name),
                    "incremental_available": False,
                    "incremental_field": None,
                    "sync_type": None,
                }
                for name, _ in sheets
            ]

            return Response(status=status.HTTP_200_OK, data=result_mapped_to_options)

        # Get schemas and validate SQL credentials
        if source_type in [
            ExternalDataSource.Type.POSTGRES,
            ExternalDataSource.Type.MYSQL,
            ExternalDataSource.Type.MSSQL,
        ]:
            # Importing pymssql requires mssql drivers to be installed locally - see posthog/warehouse/README.md
            from pymssql import OperationalError as MSSQLOperationalError

            host = request.data.get("host", None)
            port = request.data.get("port", None)
            database = request.data.get("database", None)

            user = request.data.get("user", None)
            password = request.data.get("password", None)
            schema = request.data.get("schema", None)

            ssh_tunnel_obj = request.data.get("ssh-tunnel", {})
            using_ssh_tunnel = ssh_tunnel_obj.get("enabled", False)
            ssh_tunnel_host = ssh_tunnel_obj.get("host", None)
            ssh_tunnel_port = ssh_tunnel_obj.get("port", None)
            ssh_tunnel_auth_type_obj = ssh_tunnel_obj.get("auth_type", {})
            ssh_tunnel_auth_type = ssh_tunnel_auth_type_obj.get("selection", None)
            ssh_tunnel_auth_type_username = ssh_tunnel_auth_type_obj.get("username", None)
            ssh_tunnel_auth_type_password = ssh_tunnel_auth_type_obj.get("password", None)
            ssh_tunnel_auth_type_passphrase = ssh_tunnel_auth_type_obj.get("passphrase", None)
            ssh_tunnel_auth_type_private_key = ssh_tunnel_auth_type_obj.get("private_key", None)

            using_ssl_str = request.data.get("using_ssl", "1")
            using_ssl = str_to_bool(using_ssl_str)

            ssh_tunnel = SSHTunnel(
                enabled=using_ssh_tunnel,
                host=ssh_tunnel_host,
                port=ssh_tunnel_port,
                auth_type=ssh_tunnel_auth_type,
                username=ssh_tunnel_auth_type_username,
                password=ssh_tunnel_auth_type_password,
                passphrase=ssh_tunnel_auth_type_passphrase,
                private_key=ssh_tunnel_auth_type_private_key,
            )

            if not host or not port or not database or not user or not password or not schema:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Missing required parameters: host, port, database, user, password, schema"},
                )

            if using_ssh_tunnel:
                auth_valid, auth_error_message = ssh_tunnel.is_auth_valid()
                if not auth_valid:
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={
                            "message": (
                                auth_error_message
                                if len(auth_error_message) > 0
                                else "Invalid SSH tunnel auth settings"
                            )
                        },
                    )

                port_valid, port_error_message = ssh_tunnel.has_valid_port()
                if not port_valid:
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={
                            "message": (
                                port_error_message
                                if len(port_error_message) > 0
                                else "Invalid SSH tunnel auth settings"
                            )
                        },
                    )

            # Validate internal postgres
            if not self._validate_database_host(host, self.team_id, using_ssh_tunnel):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Cannot use internal database"},
                )

            try:
                result = get_sql_schemas_for_source_type(
                    source_type,
                    {
                        "host": host,
                        "port": int(port),
                        "database": database,
                        "user": user,
                        "password": password,
                        "schema": schema,
                        "ssh_tunnel": {
                            "host": ssh_tunnel.host,
                            "port": ssh_tunnel.port,
                            "enabled": ssh_tunnel.enabled,
                            "auth": {
                                "type": ssh_tunnel.auth_type,
                                "username": ssh_tunnel.username,
                                "password": ssh_tunnel.password,
                                "private_key": ssh_tunnel.private_key,
                                "passphrase": ssh_tunnel.passphrase,
                            },
                        },
                        "using_ssl": using_ssl,
                    },
                )
                if len(result.keys()) == 0:
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": "Schema doesn't exist"},
                    )
            except OperationalError as e:
                exposed_error = self._expose_postgres_error(e)

                if exposed_error is None:
                    capture_exception(e)

                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": exposed_error or get_generic_sql_error(source_type)},
                )
            except MSSQLOperationalError as e:
                error_msg = " ".join(str(n) for n in e.args)
                exposed_error = self._expose_mssql_error(error_msg)

                if exposed_error is None:
                    capture_exception(e)

                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": exposed_error or get_generic_sql_error(source_type)},
                )
            except BaseSSHTunnelForwarderError as e:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": e.value or get_generic_sql_error(source_type)},
                )
            except Exception as e:
                capture_exception(e)
                logger.exception("Could not fetch schemas", exc_info=e)

                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": get_generic_sql_error(source_type)},
                )

            rows = {}
            if source_type == ExternalDataSource.Type.POSTGRES:
                filtered_results = [
                    (table_name, filter_postgres_incremental_fields(columns)) for table_name, columns in result.items()
                ]
                try:
                    rows = get_postgres_row_count(host, port, database, user, password, schema, ssh_tunnel)
                except:
                    pass

            elif source_type == ExternalDataSource.Type.MYSQL:
                filtered_results = [
                    (table_name, filter_mysql_incremental_fields(columns)) for table_name, columns in result.items()
                ]
            elif source_type == ExternalDataSource.Type.MSSQL:
                filtered_results = [
                    (table_name, filter_mssql_incremental_fields(columns)) for table_name, columns in result.items()
                ]

            result_mapped_to_options = [
                {
                    "table": table_name,
                    "should_sync": False,
                    "rows": rows.get(table_name, None),
                    "incremental_fields": [
                        {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                        for column_name, column_type in columns
                    ],
                    "incremental_available": True,
                    "append_available": True,
                    "incremental_field": columns[0][0] if len(columns) > 0 and len(columns[0]) > 0 else None,
                    "sync_type": None,
                }
                for table_name, columns in filtered_results
            ]
            return Response(status=status.HTTP_200_OK, data=result_mapped_to_options)
        elif source_type == ExternalDataSource.Type.MONGODB:
            from pymongo.errors import OperationFailure as MongoOperationFailure

            connection_string = request.data.get("connection_string", None)

            if not connection_string:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Missing required parameter: connection_string"},
                )

            # Parse connection string to validate and extract parameters
            try:
                from posthog.temporal.data_imports.pipelines.mongo.mongo import _parse_connection_string

                connection_params = _parse_connection_string(connection_string)
            except Exception:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": f"Invalid connection string"},
                )

            if not connection_params.get("database"):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Database name is required in connection string"},
                )

            # Validate internal database
            if not self._validate_mongo_host(connection_params):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Cannot use internal database"},
                )

            try:
                result = get_mongo_schemas(
                    MongoSourceConfig.from_dict(
                        {
                            "connection_string": connection_string,
                        }
                    )
                )
                if len(result.keys()) == 0:
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": "No collections found in database"},
                    )
            except MongoOperationFailure:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": f"MongoDB authentication failed"},
                )
            except Exception as e:
                capture_exception(e)
                logger.exception("Could not fetch MongoDB collections", exc_info=e)

                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Failed to connect to MongoDB database"},
                )

            filtered_results = [
                (collection_name, filter_mongo_incremental_fields(columns, connection_string, collection_name))
                for collection_name, columns in result.items()
            ]

            result_mapped_to_options = [
                {
                    "table": collection_name,
                    "should_sync": False,
                    "rows": None,  # MongoDB doesn't provide easy row count in schema discovery
                    "incremental_fields": [],
                    "incremental_available": False,
                    "incremental_field": None,
                    "sync_type": None,
                }
                for collection_name, _ in filtered_results
            ]
            return Response(status=status.HTTP_200_OK, data=result_mapped_to_options)
        elif source_type == ExternalDataSource.Type.SNOWFLAKE:
            account_id = request.data.get("account_id")
            database = request.data.get("database")
            warehouse = request.data.get("warehouse")
            role = request.data.get("role")
            schema = request.data.get("schema")

            auth_type_obj = request.data.get("auth_type", {})
            auth_type = auth_type_obj.get("selection", None)
            auth_type_username = auth_type_obj.get("username", None)
            auth_type_password = auth_type_obj.get("password", None)
            auth_type_passphrase = auth_type_obj.get("passphrase", None)
            auth_type_private_key = auth_type_obj.get("private_key", None)

            if not account_id or not warehouse or not database or not schema:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Missing required parameters: account id, warehouse, database, schema"},
                )

            if auth_type == "password" and (not auth_type_username or not auth_type_password):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Missing required parameters: username, password"},
                )

            if auth_type == "keypair" and (
                not auth_type_passphrase or not auth_type_private_key or not auth_type_username
            ):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Missing required parameters: passphrase, private key"},
                )

            try:
                result = get_snowflake_schemas(
                    SnowflakeSourceConfig(
                        account_id=account_id,
                        database=database,
                        warehouse=warehouse,
                        schema=schema,
                        user=auth_type_username,
                        password=auth_type_password,
                        role=role,
                        passphrase=auth_type_passphrase,
                        private_key=auth_type_private_key,
                        auth_type=auth_type,
                    )
                )
                if len(result.keys()) == 0:
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": "Snowflake schema doesn't exist"},
                    )
            except (ProgrammingError, DatabaseError, ForbiddenError) as e:
                exposed_error = self._expose_snowflake_error(e)

                if exposed_error is None:
                    capture_exception(e)

                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": exposed_error or GenericSnowflakeError},
                )
            except Exception as e:
                capture_exception(e)
                logger.exception("Could not fetch Snowflake schemas", exc_info=e)

                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": GenericSnowflakeError},
                )

            filtered_results = [
                (table_name, filter_snowflake_incremental_fields(columns)) for table_name, columns in result.items()
            ]

            result_mapped_to_options = [
                {
                    "table": table_name,
                    "should_sync": False,
                    "incremental_fields": [
                        {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                        for column_name, column_type in columns
                    ],
                    "incremental_available": True,
                    "append_available": True,
                    "incremental_field": columns[0][0] if len(columns) > 0 and len(columns[0]) > 0 else None,
                    "sync_type": None,
                }
                for table_name, columns in filtered_results
            ]
            return Response(status=status.HTTP_200_OK, data=result_mapped_to_options)

        # Return the possible endpoints for all other source types
        schemas = PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING.get(source_type, None)
        incremental_schemas = PIPELINE_TYPE_INCREMENTAL_ENDPOINTS_MAPPING.get(source_type, ())
        incremental_fields = PIPELINE_TYPE_INCREMENTAL_FIELDS_MAPPING.get(source_type, {})

        if schemas is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Invalid parameter: source_type"},
            )

        options = [
            {
                "table": row,
                "should_sync": False,
                "incremental_fields": [
                    {
                        "label": field["label"],
                        "type": field["type"],
                        "field": field["field"],
                        "field_type": field["field_type"],
                    }
                    for field in incremental_fields.get(row, [])
                ],
                "incremental_available": source_type != ExternalDataSource.Type.STRIPE and row in incremental_schemas,
                "append_available": row in incremental_schemas,
                "incremental_field": (
                    incremental_fields.get(row, [])[0]["field"] if row in incremental_schemas else None
                ),
                "sync_type": None,
            }
            for row in schemas
        ]
        return Response(status=status.HTTP_200_OK, data=options)

    @action(methods=["POST"], detail=False)
    def source_prefix(self, request: Request, *arg: Any, **kwargs: Any):
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        if self.prefix_required(source_type):
            if not prefix:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Source type already exists. Prefix is required"},
                )
            elif self.prefix_exists(source_type, prefix):
                return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Prefix already exists"})

        return Response(status=status.HTTP_200_OK)

    @action(methods=["GET"], detail=True)
    def jobs(self, request: Request, *arg: Any, **kwargs: Any):
        instance: ExternalDataSource = self.get_object()
        after = request.query_params.get("after", None)
        before = request.query_params.get("before", None)

        jobs = instance.jobs.filter(billable=True).prefetch_related("schema").order_by("-created_at")

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
        return Response(
            status=status.HTTP_200_OK,
            data={str(key): value.model_dump() for key, value in AVAILABLE_SOURCES.items()},
        )

    def _expose_postgres_error(self, error: OperationalError) -> str | None:
        error_msg = " ".join(str(n) for n in error.args)

        for key, value in PostgresErrors.items():
            if key in error_msg:
                return value
        return None

    def _expose_mssql_error(self, error: str) -> str | None:
        for key, value in MSSQLErrors.items():
            if key in error:
                return value
        return None

    def _expose_snowflake_error(self, error: ProgrammingError | DatabaseError | ForbiddenError) -> str | None:
        error_msg = error.msg or error.raw_msg or ""

        for key, value in SnowflakeErrors.items():
            if key in error_msg:
                return value
        return None

    def _validate_mongo_host(self, connection_params: dict[str, Any]) -> bool:
        """Validate MongoDB host for non-SRV connections."""
        if connection_params.get("is_srv"):
            return True  # SRV connections are always allowed

        return self._validate_database_host(connection_params["host"], self.team_id, False)

    def _validate_database_host(self, host: str, team_id: int, using_ssh_tunnel: bool) -> bool:
        if using_ssh_tunnel:
            return True

        if host.startswith("172") or host.startswith("10") or host.startswith("localhost"):
            if is_cloud():
                region = get_instance_region()
                if (region == "US" and team_id == 2) or (region == "EU" and team_id == 1):
                    return True
                else:
                    return False

        return True


class InternalPostgresError(Exception):
    pass


def parse_snowflake_job_inputs(payload: dict[str, Any]) -> dict[str, Any]:
    account_id = payload.get("account_id")
    database = payload.get("database")
    warehouse = payload.get("warehouse")
    role = payload.get("role")
    schema = payload.get("schema")

    auth_type_obj = payload.get("auth_type", {})
    auth_type = auth_type_obj.get("selection", None)
    auth_type_username = auth_type_obj.get("username", None)
    auth_type_password = auth_type_obj.get("password", None)
    auth_type_passphrase = auth_type_obj.get("passphrase", None)
    auth_type_private_key = auth_type_obj.get("private_key", None)

    return {
        "account_id": account_id,
        "database": database,
        "warehouse": warehouse,
        "role": role,
        "schema": schema,
        "auth_type": auth_type,
        "user": auth_type_username,
        "password": auth_type_password,
        "passphrase": auth_type_passphrase,
        "private_key": auth_type_private_key,
    }


def parse_bigquery_job_inputs(payload: dict[str, Any]) -> dict[str, Any]:
    key_file = payload.get("key_file", {})
    project_id = key_file.get("project_id")

    dataset_id = payload.get("dataset_id")
    # Very common to include the project_id as a prefix of the dataset_id.
    # We remove it if it's there.
    if dataset_id:
        dataset_id = dataset_id.removeprefix(f"{project_id}.")

    private_key = key_file.get("private_key")
    private_key_id = key_file.get("private_key_id")
    client_email = key_file.get("client_email")
    token_uri = key_file.get("token_uri")

    temporary_dataset = payload.get("temporary-dataset", {})
    using_temporary_dataset = temporary_dataset.get("enabled", False)
    temporary_dataset_id = temporary_dataset.get("temporary_dataset_id", None)

    dataset_project = payload.get("dataset_project", {})
    using_custom_dataset_project = dataset_project.get("enabled", False)
    dataset_project_id = dataset_project.get("dataset_project_id", None)

    job_inputs = {
        "dataset_id": dataset_id,
        "project_id": project_id,
        "private_key": private_key,
        "private_key_id": private_key_id,
        "client_email": client_email,
        "token_uri": token_uri,
        "using_temporary_dataset": using_temporary_dataset,
        "temporary_dataset_id": temporary_dataset_id,
        "using_custom_dataset_project": using_custom_dataset_project,
        "dataset_project_id": dataset_project_id,
    }

    required_inputs = {"private_key", "private_key_id", "client_email", "dataset_id", "project_id", "token_uri"}
    have_all_required = all(job_inputs.get(input_name, None) is not None for input_name in required_inputs)

    if not have_all_required:
        included_inputs = {k for k, v in job_inputs.items() if v is not None}
        missing = ", ".join(f"'{job_input}'" for job_input in required_inputs - included_inputs)
        raise ValidationError(f"Missing required BigQuery inputs: {missing}")

    return job_inputs
