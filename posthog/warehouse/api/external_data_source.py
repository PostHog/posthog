import uuid
from typing import Any, Optional

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
from posthog.temporal.data_imports.pipelines.bigquery import (
    get_schemas as get_bigquery_schemas,
)

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.cloud_utils import is_cloud
from posthog.exceptions_capture import capture_exception
from posthog.hogql.database.database import create_hogql_database
from posthog.models.user import User
from posthog.temporal.data_imports.pipelines.bigquery.handlers import BigQuerySourceHandler
from posthog.temporal.data_imports.pipelines.stripe.handlers import StripeSourceHandler
from posthog.temporal.data_imports.pipelines.chargebee.handlers import ChargebeeSourceHandler
from posthog.temporal.data_imports.pipelines.vitally.handlers import VitallySourceHandler
from posthog.temporal.data_imports.pipelines.zendesk.handlers import ZendeskSourceHandler
from posthog.temporal.data_imports.pipelines.sql_database.handlers import (
    PostgresSourceHandler,
    MySQLSourceHandler,
    MSSQLSourceHandler,
)
from posthog.temporal.data_imports.pipelines.snowflake.handlers import SnowflakeSourceHandler
from posthog.temporal.data_imports.pipelines.hubspot.handlers import HubspotSourceHandler
from posthog.temporal.data_imports.pipelines.salesforce.handlers import SalesforceSourceHandler
from posthog.temporal.data_imports.pipelines.source.handlers import SourceHandler

from posthog.temporal.data_imports.pipelines.hubspot.auth import (
    get_hubspot_access_token_from_code,
)
from posthog.temporal.data_imports.pipelines.schemas import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from posthog.utils import get_instance_region, str_to_bool
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
    get_snowflake_schemas,
    get_sql_schemas_for_source_type,
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
        if instance.status == ExternalDataJob.Status.CANCELLED:
            return "Billing limits"

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
            "use_ssl",
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
        }
        job_inputs = representation.get("job_inputs", {})
        if isinstance(job_inputs, dict):
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
        any_failures = any(schema.status == ExternalDataSchema.Status.ERROR for schema in active_schemas)
        any_cancelled = any(schema.status == ExternalDataSchema.Status.CANCELLED for schema in active_schemas)
        any_paused = any(schema.status == ExternalDataSchema.Status.PAUSED for schema in active_schemas)
        any_running = any(schema.status == ExternalDataSchema.Status.RUNNING for schema in active_schemas)
        any_completed = any(schema.status == ExternalDataSchema.Status.COMPLETED for schema in active_schemas)

        if any_failures:
            return ExternalDataSchema.Status.ERROR
        elif any_cancelled:
            return "Billing limits"
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

        if existing_job_inputs:
            new_job_inputs = validated_data.get("job_inputs", {})
            validated_data["job_inputs"] = {**existing_job_inputs, **new_job_inputs}

        updated_source: ExternalDataSource = super().update(instance, validated_data)

        return updated_source


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
        elif source_type == ExternalDataSource.Type.SNOWFLAKE:
            default_schemas = snowflake_schemas
        elif source_type == ExternalDataSource.Type.BIGQUERY:
            default_schemas = bigquery_schemas
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
            is_incremental = sync_type == "incremental"
            incremental_field = schema.get("incremental_field")
            incremental_field_type = schema.get("incremental_field_type")
            sync_time_of_day = schema.get("sync_time_of_day")

            if is_incremental and incremental_field is None:
                new_source_model.delete()
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Incremental schemas given do not have an incremental field set"},
                )

            if is_incremental and incremental_field_type is None:
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
                    if is_incremental
                    else {}
                ),
            )

            if schema.get("should_sync"):
                active_schemas.append(schema_model)

        try:
            for active_schema in active_schemas:
                sync_external_data_job_workflow(active_schema, create=True)
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
            job_inputs={"stripe_secret_key": client_secret, "stripe_account_id": account_id},
            prefix=prefix,
        )

        return new_source_model

    def _handle_vitally_source(self, request: Request, *args: Any, **kwargs: Any) -> ExternalDataSource:
        payload = request.data["payload"]
        secret_token = payload.get("secret_token")
        region = payload.get("region")
        subdomain = payload.get("subdomain", None)
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
        code = payload.get("code")
        redirect_uri = payload.get("redirect_uri")
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        access_token, refresh_token = get_hubspot_access_token_from_code(code, redirect_uri=redirect_uri)

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
                "hubspot_secret_key": access_token,
                "hubspot_refresh_token": refresh_token,
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

        using_ssl_str = payload.get("use_ssl", "1")
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

        schemas = get_sql_schemas_for_source_type(
            source_type,
            host,
            port,
            database,
            user,
            password,
            schema,
            ssh_tunnel,
            using_ssl,
        )

        return new_source_model, list(schemas.keys())

    def _handle_snowflake_source(
        self, request: Request, *args: Any, **kwargs: Any
    ) -> tuple[ExternalDataSource, list[Any]]:
        payload = request.data["payload"]
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

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

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            created_by=request.user if isinstance(request.user, User) else None,
            status="Running",
            source_type=source_type,
            job_inputs={
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
            },
            prefix=prefix,
        )

        schemas = get_snowflake_schemas(
            account_id=account_id,
            database=database,
            warehouse=warehouse,
            user=auth_type_username,
            password=auth_type_password,
            schema=schema,
            role=role,
            passphrase=auth_type_passphrase,
            private_key=auth_type_private_key,
            auth_type=auth_type,
        )

        return new_source_model, list(schemas.keys())

    def _handle_bigquery_source(
        self, request: Request, *args: Any, **kwargs: Any
    ) -> tuple[ExternalDataSource, list[Any]]:
        payload = request.data["payload"]
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

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

        temporary_dataset = request.data.get("temporary-dataset", {})
        using_temporary_dataset = temporary_dataset.get("enabled", False)
        temporary_dataset_id = temporary_dataset.get("temporary_dataset_id", None)

        job_inputs = {
            "dataset_id": dataset_id,
            "project_id": project_id,
            "private_key": private_key,
            "private_key_id": private_key_id,
            "client_email": client_email,
            "token_uri": token_uri,
            "using_temporary_dataset": using_temporary_dataset,
            "temporary_dataset_id": temporary_dataset_id,
        }

        required_inputs = {"private_key", "private_key_id", "client_email", "dataset_id", "project_id", "token_uri"}
        have_all_required = all(job_inputs.get(input_name, None) is not None for input_name in required_inputs)

        if not have_all_required:
            included_inputs = {k for k, v in job_inputs.items() if v is not None}
            missing = ", ".join(f"'{job_input}'" for job_input in required_inputs - included_inputs)
            raise ValidationError(f"Missing required BigQuery inputs: {missing}")

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

        schemas = get_bigquery_schemas(
            dataset_id=dataset_id,
            project_id=project_id,
            private_key=private_key,
            private_key_id=private_key_id,
            client_email=client_email,
            token_uri=token_uri,
        )

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

    def get_source_handler(self, source_type: str, request_data: dict) -> Optional[SourceHandler]:
        handlers = {
            ExternalDataSource.Type.STRIPE: StripeSourceHandler,
            ExternalDataSource.Type.BIGQUERY: BigQuerySourceHandler,
            ExternalDataSource.Type.ZENDESK: ZendeskSourceHandler,
            ExternalDataSource.Type.VITALLY: VitallySourceHandler,
            ExternalDataSource.Type.CHARGEBEE: ChargebeeSourceHandler,
            ExternalDataSource.Type.SNOWFLAKE: SnowflakeSourceHandler,
            ExternalDataSource.Type.HUBSPOT: HubspotSourceHandler,
            ExternalDataSource.Type.SALESFORCE: SalesforceSourceHandler,
        }

        if source_type in [
            ExternalDataSource.Type.POSTGRES,
            ExternalDataSource.Type.MYSQL,
            ExternalDataSource.Type.MSSQL,
        ]:
            sql_handlers = {
                ExternalDataSource.Type.POSTGRES: PostgresSourceHandler,
                ExternalDataSource.Type.MYSQL: MySQLSourceHandler,
                ExternalDataSource.Type.MSSQL: MSSQLSourceHandler,
            }
            handler_class = sql_handlers.get(source_type)
            return handler_class(
                request_data,
                self.team_id,
                validate_db_host=self._validate_database_host,
                expose_error=self._expose_postgres_error
                if source_type == ExternalDataSource.Type.POSTGRES
                else self._expose_mssql_error,
            )

        handler_class = handlers.get(source_type)
        if not handler_class:
            return None

        return handler_class(request_data, self.team_id)

    @action(methods=["POST"], detail=False)
    def database_schema(self, request: Request, *arg: Any, **kwargs: Any):
        source_type = request.data.get("source_type", None)

        if source_type is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Missing required parameter: source_type"},
            )

        handler = self.get_source_handler(source_type, request.data)
        if not handler:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Unsupported source type: {source_type}"},
            )

        try:
            # Validate credentials
            is_valid, error_message = handler.validate_credentials()
            if not is_valid:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": error_message},
                )

            # Get schema options
            options = handler.get_schema_options()
            return Response(status=status.HTTP_200_OK, data=options)

        except ValidationError as e:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": str(e)},
            )
        except Exception as e:
            capture_exception(e)
            logger.exception(f"Error handling database schema for source type {source_type}", exc_info=e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Error handling source type {source_type}"},
            )

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

    @action(methods=["POST"], detail=True)
    def check_schema_changes(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSource = self.get_object()
        source_type = instance.source_type

        handler = self.get_source_handler(source_type, instance.job_inputs)
        if not handler:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Unsupported source type: {source_type}"},
            )

        try:
            # Validate credentials are still valid
            is_valid, error_message = handler.validate_credentials()
            if not is_valid:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": error_message},
                )

            # Get current schema options from source
            current_schemas = handler.get_schema_options()
            current_schemas = [schema["table"] for schema in current_schemas]

            # Get existing schemas from database
            existing_schemas = list(
                ExternalDataSchema.objects.filter(source=instance).exclude(deleted=True).values_list("name", flat=True)
            )

            # Find new schemas (in source but not in db)
            new_schemas = []
            for schema_name in current_schemas:
                if schema_name not in existing_schemas:
                    new_schemas.append(schema_name)

            # Find removed schemas (in db but not in source)
            removed_schemas = []
            for schema_name in existing_schemas:
                if schema_name not in current_schemas:
                    removed_schemas.append(schema_name)

            return Response(
                status=status.HTTP_200_OK,
                data={
                    "has_changes": len(new_schemas) > 0 or len(removed_schemas) > 0,
                    "new_schemas": new_schemas,
                    "removed_schemas": removed_schemas,
                    "existing_schemas": existing_schemas,
                    "current_schemas": current_schemas,
                },
            )

        except Exception as e:
            capture_exception(e)
            logger.exception(f"Error checking schema changes for source type {source_type}", exc_info=e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Error checking schema changes: {str(e)}"},
            )


class InternalPostgresError(Exception):
    pass
