from rest_framework import serializers
import structlog
import temporalio
from posthog.temporal.data_imports.pipelines.schemas import PIPELINE_TYPE_INCREMENTAL_FIELDS_MAPPING
from posthog.temporal.data_imports.pipelines.bigquery import (
    get_schemas as get_bigquery_schemas,
    filter_incremental_fields as filter_bigquery_incremental_fields,
)
from posthog.warehouse.models import ExternalDataSchema, ExternalDataJob
from typing import Optional, Any
from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework import viewsets, filters, status
from posthog.api.utils import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from posthog.hogql.database.database import create_hogql_database
from posthog.api.log_entries import LogEntryMixin

from posthog.warehouse.data_load.service import (
    external_data_workflow_exists,
    is_any_external_data_schema_paused,
    sync_external_data_job_workflow,
    pause_external_data_schedule,
    trigger_external_data_workflow,
    unpause_external_data_schedule,
    cancel_external_data_workflow,
)
from posthog.warehouse.models.external_data_schema import (
    filter_mssql_incremental_fields,
    filter_mysql_incremental_fields,
    filter_postgres_incremental_fields,
    filter_snowflake_incremental_fields,
    get_snowflake_schemas,
    get_sql_schemas_for_source_type,
    sync_frequency_interval_to_sync_frequency,
    sync_frequency_to_sync_frequency_interval,
)
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.ssh_tunnel import SSHTunnel
from posthog.warehouse.types import IncrementalField

logger = structlog.get_logger(__name__)


class ExternalDataSchemaSerializer(serializers.ModelSerializer):
    table = serializers.SerializerMethodField(read_only=True)
    incremental = serializers.SerializerMethodField(read_only=True)
    sync_type = serializers.SerializerMethodField(read_only=True)
    incremental_field = serializers.SerializerMethodField(read_only=True)
    incremental_field_type = serializers.SerializerMethodField(read_only=True)
    sync_frequency = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ExternalDataSchema

        fields = [
            "id",
            "name",
            "table",
            "should_sync",
            "last_synced_at",
            "latest_error",
            "incremental",
            "status",
            "sync_type",
            "incremental_field",
            "incremental_field_type",
            "sync_frequency",
        ]

        read_only_fields = [
            "id",
            "name",
            "table",
            "last_synced_at",
            "latest_error",
            "status",
        ]

    def get_status(self, schema: ExternalDataSchema) -> str | None:
        if schema.status == ExternalDataSchema.Status.CANCELLED:
            return "Billing limits"

        return schema.status

    def get_incremental(self, schema: ExternalDataSchema) -> bool:
        return schema.is_incremental

    def get_incremental_field(self, schema: ExternalDataSchema) -> str | None:
        return schema.sync_type_config.get("incremental_field")

    def get_incremental_field_type(self, schema: ExternalDataSchema) -> str | None:
        return schema.sync_type_config.get("incremental_field_type")

    def get_sync_type(self, schema: ExternalDataSchema) -> ExternalDataSchema.SyncType | None:
        return schema.sync_type

    def get_table(self, schema: ExternalDataSchema) -> Optional[dict]:
        from posthog.warehouse.api.table import SimpleTableSerializer

        hogql_context = self.context.get("database", None)
        if not hogql_context:
            hogql_context = create_hogql_database(team_id=self.context["team_id"])

        return SimpleTableSerializer(schema.table, context={"database": hogql_context}).data or None

    def get_sync_frequency(self, schema: ExternalDataSchema):
        return sync_frequency_interval_to_sync_frequency(schema)

    def update(self, instance: ExternalDataSchema, validated_data: dict[str, Any]) -> ExternalDataSchema:
        data = self.context["request"].data

        sync_type = data.get("sync_type")

        if (
            sync_type is not None
            and sync_type != ExternalDataSchema.SyncType.FULL_REFRESH
            and sync_type != ExternalDataSchema.SyncType.INCREMENTAL
        ):
            raise ValidationError("Invalid sync type")

        validated_data["sync_type"] = sync_type

        # Check whether we need a full table refresh
        trigger_refresh = False
        if instance.sync_type is not None and sync_type is not None:
            # If sync type changes
            if instance.sync_type != sync_type:
                trigger_refresh = True

            # If sync type is incremental and the incremental field changes
            if sync_type == ExternalDataSchema.SyncType.INCREMENTAL and instance.sync_type_config.get(
                "incremental_field"
            ) != data.get("incremental_field"):
                trigger_refresh = True

        # Update the validated_data with incremental fields
        if sync_type == "incremental":
            payload = instance.sync_type_config
            payload["incremental_field"] = data.get("incremental_field")
            payload["incremental_field_type"] = data.get("incremental_field_type")

            validated_data["sync_type_config"] = payload
        else:
            payload = instance.sync_type_config
            payload.pop("incremental_field", None)
            payload.pop("incremental_field_type", None)

            validated_data["sync_type_config"] = payload

        should_sync = validated_data.get("should_sync", None)
        sync_frequency = data.get("sync_frequency", None)
        was_sync_frequency_updated = False

        if sync_frequency:
            sync_frequency_interval = sync_frequency_to_sync_frequency_interval(sync_frequency)

            if sync_frequency_interval != instance.sync_frequency_interval:
                was_sync_frequency_updated = True
                validated_data["sync_frequency_interval"] = sync_frequency_interval
                instance.sync_frequency_interval = sync_frequency_interval

        if should_sync is True and sync_type is None and instance.sync_type is None:
            raise ValidationError("Sync type must be set up first before enabling schema")

        schedule_exists = external_data_workflow_exists(str(instance.id))

        if schedule_exists:
            if should_sync is False:
                pause_external_data_schedule(str(instance.id))
            elif should_sync is True:
                unpause_external_data_schedule(str(instance.id))
        else:
            if should_sync is True:
                sync_external_data_job_workflow(instance, create=True)

        if was_sync_frequency_updated:
            sync_external_data_job_workflow(instance, create=False)

        if trigger_refresh:
            source: ExternalDataSource = instance.source
            source.job_inputs.update({"reset_pipeline": True})
            source.save()
            trigger_external_data_workflow(instance)

        return super().update(instance, validated_data)


class SimpleExternalDataSchemaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalDataSchema
        fields = ["id", "name", "should_sync", "last_synced_at"]


class ExternalDataSchemaViewset(TeamAndOrgViewSetMixin, LogEntryMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ExternalDataSchema.objects.all()
    serializer_class = ExternalDataSchemaSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    ordering = "-created_at"
    log_source = "external_data_jobs"

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["database"] = create_hogql_database(team_id=self.team_id)
        return context

    def safely_get_queryset(self, queryset):
        return queryset.exclude(deleted=True).prefetch_related("created_by").order_by(self.ordering)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSchema = self.get_object()

        if instance.table:
            instance.table.soft_delete()
        instance.soft_delete()

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["POST"], detail=True)
    def reload(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()

        if is_any_external_data_schema_paused(self.team_id):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please increase your billing limit to resume syncing."},
            )

        try:
            trigger_external_data_workflow(instance)
        except temporalio.service.RPCError as e:
            logger.exception(f"Could not trigger external data job for schema {instance.id}", exc_info=e)

        except Exception as e:
            logger.exception(f"Could not trigger external data job for schema {instance.id}", exc_info=e)
            raise

        instance.status = ExternalDataSchema.Status.RUNNING
        instance.save()
        return Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    def resync(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()

        if is_any_external_data_schema_paused(self.team_id):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please increase your billing limit to resume syncing."},
            )

        latest_running_job = (
            ExternalDataJob.objects.filter(schema_id=instance.pk, team_id=instance.team_id)
            .order_by("-created_at")
            .first()
        )

        if latest_running_job and latest_running_job.workflow_id and latest_running_job.status == "Running":
            cancel_external_data_workflow(latest_running_job.workflow_id)

        source: ExternalDataSource = instance.source
        source.job_inputs.update({"reset_pipeline": True})
        source.save()

        try:
            trigger_external_data_workflow(instance)
        except temporalio.service.RPCError as e:
            logger.exception(f"Could not trigger external data job for schema {instance.id}", exc_info=e)

        instance.status = ExternalDataSchema.Status.RUNNING
        instance.save()
        return Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    def incremental_fields(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()
        source: ExternalDataSource = instance.source
        incremental_columns: list[IncrementalField] = []

        if source.source_type in [
            ExternalDataSource.Type.POSTGRES,
            ExternalDataSource.Type.MYSQL,
            ExternalDataSource.Type.MSSQL,
        ]:
            # TODO(@Gilbert09): Move all this into a util and replace elsewhere
            host = source.job_inputs.get("host")
            port = source.job_inputs.get("port")
            user = source.job_inputs.get("user")
            password = source.job_inputs.get("password")
            database = source.job_inputs.get("database")
            pg_schema = source.job_inputs.get("schema")

            using_ssh_tunnel = str(source.job_inputs.get("ssh_tunnel_enabled", False)) == "True"
            ssh_tunnel_host = source.job_inputs.get("ssh_tunnel_host")
            ssh_tunnel_port = source.job_inputs.get("ssh_tunnel_port")
            ssh_tunnel_auth_type = source.job_inputs.get("ssh_tunnel_auth_type")
            ssh_tunnel_auth_type_username = source.job_inputs.get("ssh_tunnel_auth_type_username")
            ssh_tunnel_auth_type_password = source.job_inputs.get("ssh_tunnel_auth_type_password")
            ssh_tunnel_auth_type_passphrase = source.job_inputs.get("ssh_tunnel_auth_type_passphrase")
            ssh_tunnel_auth_type_private_key = source.job_inputs.get("ssh_tunnel_auth_type_private_key")

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

            db_schemas = get_sql_schemas_for_source_type(
                source.source_type,
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                schema=pg_schema,
                ssh_tunnel=ssh_tunnel,
            )

            columns = db_schemas.get(instance.name, [])
            if source.source_type == ExternalDataSource.Type.POSTGRES:
                incremental_fields_func = filter_postgres_incremental_fields
            elif source.source_type == ExternalDataSource.Type.MYSQL:
                incremental_fields_func = filter_mysql_incremental_fields
            elif source.source_type == ExternalDataSource.Type.MSSQL:
                incremental_fields_func = filter_mssql_incremental_fields

            incremental_columns = [
                {"field": name, "field_type": field_type, "label": name, "type": field_type}
                for name, field_type in incremental_fields_func(columns)
            ]
        elif source.source_type == ExternalDataSource.Type.SNOWFLAKE:
            # TODO(@Gilbert09): Move all this into a util and replace elsewhere
            account_id = source.job_inputs.get("account_id")
            user = source.job_inputs.get("user")
            password = source.job_inputs.get("password")
            database = source.job_inputs.get("database")
            warehouse = source.job_inputs.get("warehouse")
            sf_schema = source.job_inputs.get("schema")
            role = source.job_inputs.get("role")

            sf_schemas = get_snowflake_schemas(
                account_id=account_id,
                database=database,
                warehouse=warehouse,
                user=user,
                password=password,
                schema=sf_schema,
                role=role,
            )

            columns = sf_schemas.get(instance.name, [])
            incremental_columns = [
                {"field": name, "field_type": field_type, "label": name, "type": field_type}
                for name, field_type in filter_snowflake_incremental_fields(columns)
            ]
        elif source.source_type == ExternalDataSource.Type.BIGQUERY:
            dataset_id = source.job_inputs.get("dataset_id")
            project_id = source.job_inputs.get("project_id")
            private_key = source.job_inputs.get("private_key")
            private_key_id = source.job_inputs.get("private_key_id")
            client_email = source.job_inputs.get("client_email")
            token_uri = source.job_inputs.get("token_uri")

            bq_schemas = get_bigquery_schemas(
                dataset_id=dataset_id,
                project_id=project_id,
                private_key=private_key,
                private_key_id=private_key_id,
                client_email=client_email,
                token_uri=token_uri,
            )

            columns = bq_schemas.get(instance.name, [])
            incremental_columns = [
                {"field": name, "field_type": field_type, "label": name, "type": field_type}
                for name, field_type in filter_bigquery_incremental_fields(columns)
            ]
        else:
            mapping = PIPELINE_TYPE_INCREMENTAL_FIELDS_MAPPING.get(source.source_type)
            if mapping is None:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": f'Source type "{source.source_type}" not found'},
                )
            mapping_fields = mapping.get(instance.name, [])

            incremental_columns = mapping_fields

        return Response(status=status.HTTP_200_OK, data=incremental_columns)
