import datetime as dt
import dataclasses
from typing import Any, Optional

from django.dispatch import receiver

import structlog
import temporalio
from rest_framework import filters, serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql.database.database import Database

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal
from posthog.temporal.data_imports.sources import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
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
    sync_frequency_interval_to_sync_frequency,
    sync_frequency_to_sync_frequency_interval,
)
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.types import ExternalDataSourceType

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
            hogql_context = Database.create_for(team_id=self.context["team_id"])

        if schema.table and schema.table.deleted:
            return None

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


class ExternalDataSchemaViewset(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ExternalDataSchema.objects.all()
    serializer_class = ExternalDataSchemaSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    ordering = "-created_at"

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["database"] = Database.create_for(team_id=self.team_id)
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

        if not source.job_inputs:
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Missing job inputs"})

        if not source.source_type:
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Missing source type"})

        source_type_enum = ExternalDataSourceType(source.source_type)

        new_source = SourceRegistry.get_source(source_type_enum)
        config = new_source.parse_config(source.job_inputs)

        logger.debug(f"Validating credentials for {source_type_enum}")
        credentials_valid, credentials_error = new_source.validate_credentials(config, self.team_id)
        if not credentials_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": credentials_error or "Invalid credentials"},
            )

        try:
            logger.debug(f"Retrieving schemas for {source_type_enum}")
            schemas = new_source.get_schemas(config, self.team_id)
        except Exception as e:
            capture_exception(e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": str(e)},
            )

        schema: SourceSchema | None = None

        for s in schemas:
            if s.name == instance.name:
                schema = s
                break

        if schema is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"message": f"Schema with name {instance.name} not found"}
            )

        data = {
            "incremental_fields": schema.incremental_fields,
            "incremental_available": schema.supports_incremental,
            "append_available": schema.supports_append,
            "full_refresh_available": True,
        }

        return Response(status=status.HTTP_200_OK, data=data)


@dataclasses.dataclass(frozen=True)
class ExternalDataSchemaContext(ActivityContextBase):
    name: str
    sync_type: str | None
    sync_frequency: str | None
    source_id: str
    source_type: str


@receiver(model_activity_signal, sender=ExternalDataSchema)
def handle_external_data_schema_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    if activity == "created":
        # We don't want to log the creation of schemas as they get bulk created on source creation
        return

    external_data_schema = after_update or before_update

    if not external_data_schema:
        return

    source = external_data_schema.source
    source_type = source.source_type if source else ""

    sync_frequency = None
    if external_data_schema.sync_frequency_interval:
        from posthog.warehouse.models.external_data_schema import sync_frequency_interval_to_sync_frequency

        sync_frequency = sync_frequency_interval_to_sync_frequency(external_data_schema.sync_frequency_interval)

    context = ExternalDataSchemaContext(
        name=external_data_schema.name or "",
        sync_type=external_data_schema.sync_type,
        sync_frequency=sync_frequency,
        source_id=str(source.id) if source else "",
        source_type=source_type,
    )

    log_activity(
        organization_id=external_data_schema.team.organization_id,
        team_id=external_data_schema.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=external_data_schema.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=external_data_schema.name,
            context=context,
        ),
    )
