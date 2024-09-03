from dateutil import parser
import uuid
from typing import Any

from psycopg2 import OperationalError
from sentry_sdk import capture_exception
import structlog
from rest_framework import filters, serializers, status, viewsets
from posthog.api.utils import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.warehouse.data_load.service import (
    sync_external_data_job_workflow,
    delete_external_data_schedule,
    cancel_external_data_workflow,
    delete_data_import_folder,
    is_any_external_data_schema_paused,
    trigger_external_data_source_workflow,
)
from posthog.warehouse.models import ExternalDataSource, ExternalDataSchema, ExternalDataJob
from posthog.warehouse.api.external_data_schema import ExternalDataSchemaSerializer, SimpleExternalDataSchemaSerializer
from posthog.hogql.database.database import create_hogql_database
from posthog.temporal.data_imports.pipelines.stripe import validate_credentials as validate_stripe_credentials
from posthog.temporal.data_imports.pipelines.zendesk import validate_credentials as validate_zendesk_credentials
from posthog.temporal.data_imports.pipelines.schemas import (
    PIPELINE_TYPE_INCREMENTAL_ENDPOINTS_MAPPING,
    PIPELINE_TYPE_INCREMENTAL_FIELDS_MAPPING,
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from posthog.temporal.data_imports.pipelines.hubspot.auth import (
    get_hubspot_access_token_from_code,
)
from posthog.warehouse.models.external_data_schema import (
    filter_mssql_incremental_fields,
    filter_mysql_incremental_fields,
    filter_postgres_incremental_fields,
    filter_snowflake_incremental_fields,
    get_sql_schemas_for_source_type,
    get_snowflake_schemas,
)

import temporalio

from posthog.cloud_utils import is_cloud
from posthog.utils import get_instance_region
from posthog.warehouse.models.ssh_tunnel import SSHTunnel
from sshtunnel import BaseSSHTunnelForwarderError
from snowflake.connector.errors import ProgrammingError, DatabaseError, ForbiddenError
from django.db.models import Prefetch


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

    def get_schema(self, instance: ExternalDataJob):
        return SimpleExternalDataSchemaSerializer(
            instance.schema, many=False, read_only=True, context=self.context
        ).data


class ExternalDataSourceSerializers(serializers.ModelSerializer):
    account_id = serializers.CharField(write_only=True)
    client_secret = serializers.CharField(write_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)
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
            "prefix",
            "last_run_at",
            "schemas",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "status",
            "source_type",
            "last_run_at",
            "schemas",
            "prefix",
        ]

    def get_last_run_at(self, instance: ExternalDataSource) -> str:
        latest_completed_run = instance.ordered_jobs[0] if instance.ordered_jobs else None  # type: ignore

        return latest_completed_run.created_at if latest_completed_run else None

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
            return ExternalDataSchema.Status.CANCELLED
        elif any_paused:
            return ExternalDataSchema.Status.PAUSED
        elif any_running:
            return ExternalDataSchema.Status.RUNNING
        elif any_completed:
            return ExternalDataSchema.Status.COMPLETED
        else:
            # Fallback during migration phase of going from source -> schema as the source of truth for syncs
            return instance.status

    def get_schemas(self, instance: ExternalDataSource):
        return ExternalDataSchemaSerializer(instance.schemas, many=True, read_only=True, context=self.context).data

    def update(self, instance: ExternalDataSource, validated_data: Any) -> Any:
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
                    queryset=ExternalDataJob.objects.filter(status="Completed").order_by("-created_at"),
                    to_attr="ordered_jobs",
                ),
                Prefetch(
                    "schemas",
                    queryset=ExternalDataSchema.objects.exclude(deleted=True)
                    .select_related("table__credential", "table__external_data_source")
                    .order_by("name"),
                ),
                Prefetch(
                    "schemas",
                    queryset=ExternalDataSchema.objects.exclude(deleted=True)
                    .filter(should_sync=True)
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

        # TODO: remove dummy vars
        if source_type == ExternalDataSource.Type.STRIPE:
            new_source_model = self._handle_stripe_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.HUBSPOT:
            new_source_model = self._handle_hubspot_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.ZENDESK:
            new_source_model = self._handle_zendesk_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.SALESFORCE:
            new_source_model = self._handle_salesforce_source(request, *args, **kwargs)
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
                sync_type_config={
                    "incremental_field": incremental_field,
                    "incremental_field_type": incremental_field_type,
                }
                if is_incremental
                else {},
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
        client_secret = payload.get("client_secret")
        account_id = payload.get("account_id", None)
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]

        # TODO: remove dummy vars
        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            status="Running",
            source_type=source_type,
            job_inputs={"stripe_secret_key": client_secret, "stripe_account_id": account_id},
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
        integration_id = payload.get("integration_id")

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            status="Running",
            source_type=source_type,
            job_inputs={
                "salesforce_integration_id": integration_id,
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
        database = payload.get("dbname")

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

        if not self._validate_database_host(host, self.team_id, using_ssh_tunnel):
            raise InternalPostgresError()

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
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
        )

        return new_source_model, schemas

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
        user = payload.get("user")
        password = payload.get("password")
        schema = payload.get("schema")

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=self.team,
            status="Running",
            source_type=source_type,
            job_inputs={
                "account_id": account_id,
                "database": database,
                "warehouse": warehouse,
                "role": role,
                "user": user,
                "password": password,
                "schema": schema,
            },
            prefix=prefix,
        )

        schemas = get_snowflake_schemas(account_id, database, warehouse, user, password, schema, role)

        return new_source_model, schemas

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

        all_jobs = ExternalDataJob.objects.filter(
            pipeline_id=instance.pk, team_id=instance.team_id, status="Completed"
        ).all()
        for job in all_jobs:
            try:
                delete_data_import_folder(job.folder_path())
            except Exception as e:
                logger.exception(f"Could not clean up data import folder: {job.folder_path()}", exc_info=e)
                pass

        for schema in (
            ExternalDataSchema.objects.exclude(deleted=True)
            .filter(team_id=self.team_id, source_id=instance.id, should_sync=True)
            .all()
        ):
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
            key = request.data.get("client_secret", "")
            if not validate_stripe_credentials(api_key=key):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Invalid credentials: Stripe secret is incorrect"},
                )
        elif source_type == ExternalDataSource.Type.ZENDESK:
            subdomain = request.data.get("subdomain", "")
            api_key = request.data.get("api_key", "")
            email_address = request.data.get("email_address", "")
            if not validate_zendesk_credentials(subdomain=subdomain, api_key=api_key, email_address=email_address):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Invalid credentials: Zendesk credentials are incorrect"},
                )

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
            database = request.data.get("dbname", None)

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
                            "message": auth_error_message
                            if len(auth_error_message) > 0
                            else "Invalid SSH tunnel auth settings"
                        },
                    )

                port_valid, port_error_message = ssh_tunnel.has_valid_port()
                if not port_valid:
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={
                            "message": port_error_message
                            if len(port_error_message) > 0
                            else "Invalid SSH tunnel auth settings"
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
                    host,
                    port,
                    database,
                    user,
                    password,
                    schema,
                    ssh_tunnel,
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

            if source_type == ExternalDataSource.Type.POSTGRES:
                filtered_results = [
                    (table_name, filter_postgres_incremental_fields(columns)) for table_name, columns in result.items()
                ]
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
                    "incremental_fields": [
                        {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                        for column_name, column_type in columns
                    ],
                    "incremental_available": True,
                    "incremental_field": columns[0][0] if len(columns) > 0 and len(columns[0]) > 0 else None,
                    "sync_type": None,
                }
                for table_name, columns in filtered_results
            ]
            return Response(status=status.HTTP_200_OK, data=result_mapped_to_options)
        elif source_type == ExternalDataSource.Type.SNOWFLAKE:
            account_id = request.data.get("account_id")
            database = request.data.get("database")
            warehouse = request.data.get("warehouse")
            role = request.data.get("role")
            user = request.data.get("user")
            password = request.data.get("password")
            schema = request.data.get("schema")

            if not account_id or not warehouse or not database or not user or not password or not schema:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": "Missing required parameters: account id, warehouse, database, user, password, schema"
                    },
                )

            try:
                result = get_snowflake_schemas(account_id, database, warehouse, user, password, schema, role)
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
                "incremental_available": row in incremental_schemas,
                "incremental_field": incremental_fields.get(row, [])[0]["field"]
                if row in incremental_schemas
                else None,
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

        jobs = instance.jobs.prefetch_related("schema").order_by("-created_at")

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


class InternalPostgresError(Exception):
    pass
