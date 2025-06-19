import datetime as dt
from typing import Any, Optional

import structlog
import temporalio
from rest_framework import filters, serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.hogql.database.database import create_hogql_database
from posthog.temporal.data_imports.pipelines.bigquery import (
    BigQuerySourceConfig,
    filter_incremental_fields as filter_bigquery_incremental_fields,
    get_schemas as get_bigquery_schemas,
)
from posthog.temporal.data_imports.pipelines.doit.source import DOIT_INCREMENTAL_FIELDS
from posthog.temporal.data_imports.pipelines.mssql import (
    MSSQLSourceConfig,
    get_schemas as get_mssql_schemas,
)
from posthog.temporal.data_imports.pipelines.mysql import (
    MySQLSourceConfig,
    get_schemas as get_mysql_schemas,
)
from posthog.temporal.data_imports.pipelines.postgres import (
    PostgreSQLSourceConfig,
    get_schemas as get_postgres_schemas,
)
from posthog.temporal.data_imports.pipelines.schemas import (
    PIPELINE_TYPE_INCREMENTAL_FIELDS_MAPPING,
)
from posthog.temporal.data_imports.pipelines.snowflake import (
    SnowflakeSourceConfig,
    get_schemas as get_snowflake_schemas,
)
from posthog.warehouse.data_load.service import (
    cancel_external_data_workflow,
    external_data_workflow_exists,
    is_any_external_data_schema_paused,
    pause_external_data_schedule,
    sync_external_data_job_workflow,
    trigger_external_data_workflow,
    unpause_external_data_schedule,
)
from posthog.warehouse.models import ExternalDataJob, ExternalDataSchema
from posthog.warehouse.models.external_data_schema import (
    filter_mssql_incremental_fields,
    filter_mysql_incremental_fields,
    filter_postgres_incremental_fields,
    filter_snowflake_incremental_fields,
    sync_frequency_interval_to_sync_frequency,
    sync_frequency_to_sync_frequency_interval,
)
from posthog.warehouse.models.external_data_source import ExternalDataSource
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
    sync_time_of_day = serializers.SerializerMethodField(read_only=True)

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
            "sync_time_of_day",
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
        if schema.status == ExternalDataSchema.Status.BILLING_LIMIT_REACHED:
            return "Billing limits"

        if schema.status == ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW:
            return "Billing limits too low"

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
        return sync_frequency_interval_to_sync_frequency(schema.sync_frequency_interval)

    def get_sync_time_of_day(self, schema: ExternalDataSchema):
        return schema.sync_time_of_day

    def update(self, instance: ExternalDataSchema, validated_data: dict[str, Any]) -> ExternalDataSchema:
        data = self.context["request"].data

        sync_type = data.get("sync_type")

        if (
            sync_type is not None
            and sync_type != ExternalDataSchema.SyncType.FULL_REFRESH
            and sync_type != ExternalDataSchema.SyncType.INCREMENTAL
            and sync_type != ExternalDataSchema.SyncType.APPEND
        ):
            raise ValidationError("Invalid sync type")

        validated_data["sync_type"] = sync_type

        trigger_refresh = False
        # Update the validated_data with incremental fields
        if sync_type == ExternalDataSchema.SyncType.INCREMENTAL or sync_type == ExternalDataSchema.SyncType.APPEND:
            incremental_field_changed = (
                instance.sync_type_config.get("incremental_field") != data.get("incremental_field")
                or instance.sync_type_config.get("incremental_field_last_value") is None
            )

            payload = instance.sync_type_config
            payload["incremental_field"] = data.get("incremental_field")
            payload["incremental_field_type"] = data.get("incremental_field_type")

            # If the incremental field has changed
            if incremental_field_changed:
                if instance.table is not None:
                    # Get the max_value and set it on incremental_field_last_value
                    max_value = instance.table.get_max_value_for_column(data.get("incremental_field"))
                    if max_value:
                        instance.update_incremental_field_value(max_value, save=False)
                    else:
                        # if we can't get the max value, reset the table
                        payload["incremental_field_last_value"] = None
                        trigger_refresh = True

            validated_data["sync_type_config"] = payload
        else:
            # No need to update sync_type_config for full refresh sync_type - it'll happen on the next sync
            pass

        should_sync = validated_data.get("should_sync", None)
        sync_frequency = data.get("sync_frequency", None)
        sync_time_of_day = data.get("sync_time_of_day", None)
        was_sync_frequency_updated = False
        was_sync_time_of_day_updated = False

        if sync_frequency:
            sync_frequency_interval = sync_frequency_to_sync_frequency_interval(sync_frequency)

            if sync_frequency_interval != instance.sync_frequency_interval:
                was_sync_frequency_updated = True
                validated_data["sync_frequency_interval"] = sync_frequency_interval
                instance.sync_frequency_interval = sync_frequency_interval

        if sync_time_of_day is not None:
            try:
                new_time = dt.datetime.strptime(str(sync_time_of_day), "%H:%M:%S").time()
            except ValueError:
                raise ValidationError("Invalid sync time of day")

            if new_time != instance.sync_time_of_day:
                was_sync_time_of_day_updated = True
                validated_data["sync_time_of_day"] = sync_time_of_day
                instance.sync_time_of_day = sync_time_of_day

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
                sync_external_data_job_workflow(instance, create=True, should_sync=should_sync)

        if was_sync_frequency_updated or was_sync_time_of_day_updated:
            sync_external_data_job_workflow(instance, create=False, should_sync=should_sync)

        if trigger_refresh:
            instance.sync_type_config.update({"reset_pipeline": True})
            validated_data["sync_type_config"].update({"reset_pipeline": True})

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

        instance.sync_type_config.update({"reset_pipeline": True})

        try:
            trigger_external_data_workflow(instance)
        except temporalio.service.RPCError as e:
            logger.exception(f"Could not trigger external data job for schema {instance.id}", exc_info=e)

        instance.status = ExternalDataSchema.Status.RUNNING
        instance.save()
        return Response(status=status.HTTP_200_OK)

    @action(methods=["DELETE"], detail=True)
    def delete_data(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()
        instance.delete_table()

        return Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    def incremental_fields(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()
        source: ExternalDataSource = instance.source
        incremental_columns: list[IncrementalField] = []

        if source.source_type == ExternalDataSource.Type.POSTGRES:
            db_schemas = get_postgres_schemas(PostgreSQLSourceConfig.from_dict(source.job_inputs))
            columns = db_schemas.get(instance.name, [])
            incremental_columns = [
                {"field": name, "field_type": field_type, "label": name, "type": field_type}
                for name, field_type in filter_postgres_incremental_fields(columns)
            ]

        elif source.source_type == ExternalDataSource.Type.MYSQL:
            db_schemas = get_mysql_schemas(MySQLSourceConfig.from_dict(source.job_inputs))
            columns = db_schemas.get(instance.name, [])
            incremental_columns = [
                {"field": name, "field_type": field_type, "label": name, "type": field_type}
                for name, field_type in filter_mysql_incremental_fields(columns)
            ]

        elif source.source_type == ExternalDataSource.Type.MSSQL:
            db_schemas = get_mssql_schemas(MSSQLSourceConfig.from_dict(source.job_inputs))
            columns = db_schemas.get(instance.name, [])
            incremental_columns = [
                {"field": name, "field_type": field_type, "label": name, "type": field_type}
                for name, field_type in filter_mssql_incremental_fields(columns)
            ]

        elif source.source_type == ExternalDataSource.Type.BIGQUERY:
            db_schemas = get_bigquery_schemas(BigQuerySourceConfig.from_dict(source.job_inputs), logger=logger)
            columns = db_schemas.get(instance.name, [])
            incremental_columns = [
                {"field": name, "field_type": field_type, "label": name, "type": field_type}
                for name, field_type in filter_bigquery_incremental_fields(columns)
            ]

        elif source.source_type == ExternalDataSource.Type.SNOWFLAKE:
            sf_schemas = get_snowflake_schemas(SnowflakeSourceConfig.from_dict(source.job_inputs))
            columns = sf_schemas.get(instance.name, [])
            incremental_columns = [
                {"field": name, "field_type": field_type, "label": name, "type": field_type}
                for name, field_type in filter_snowflake_incremental_fields(columns)
            ]
        elif source.source_type == ExternalDataSource.Type.DOIT:
            incremental_columns = DOIT_INCREMENTAL_FIELDS

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
