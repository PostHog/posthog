import datetime as dt
import dataclasses
from collections.abc import Callable
from typing import Any, Optional

import structlog
import temporalio
from drf_spectacular.utils import extend_schema_field
from rest_framework import filters, serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql.database.database import Database

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.temporal.data_imports.sources import SourceRegistry
from posthog.temporal.data_imports.sources.common.base import WebhookSource
from posthog.temporal.data_imports.sources.postgres.cdc.config import PostgresCDCConfig

from products.data_warehouse.backend.data_load.service import (
    cancel_external_data_workflow,
    external_data_workflow_exists,
    is_any_external_data_schema_paused,
    is_cdc_enabled_for_team,
    pause_external_data_schedule,
    sync_cdc_extraction_schedule,
    sync_external_data_job_workflow,
    trigger_external_data_workflow,
    unpause_external_data_schedule,
)
from products.data_warehouse.backend.direct_postgres import (
    get_direct_postgres_location,
    hide_direct_postgres_table,
    postgres_schema_metadata_to_dwh_columns,
    upsert_direct_postgres_table,
)
from products.data_warehouse.backend.external_data_source.webhooks import (
    create_and_register_webhook,
    get_or_create_webhook_hog_function,
)
from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataSchema
from products.data_warehouse.backend.models.external_data_schema import (
    sync_frequency_interval_to_sync_frequency,
    sync_frequency_to_sync_frequency_interval,
)
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType

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
    primary_key_columns = serializers.SerializerMethodField(read_only=True)
    cdc_table_mode = serializers.SerializerMethodField(read_only=False)

    class Meta:
        model = ExternalDataSchema

        fields = [
            "id",
            "name",
            "label",
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
            "description",
            "primary_key_columns",
            "cdc_table_mode",
        ]

        read_only_fields = [
            "id",
            "name",
            "label",
            "table",
            "last_synced_at",
            "latest_error",
            "status",
            "description",
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
        return ExternalDataSchema.SyncType(schema.sync_type) if schema.sync_type is not None else None

    def get_primary_key_columns(self, schema: ExternalDataSchema) -> list[str] | None:
        return schema.primary_key_columns

    def get_table(self, schema: ExternalDataSchema) -> Optional[dict]:
        from products.data_warehouse.backend.api.table import SimpleTableSerializer

        hogql_context = self.context.get("database", None)
        if not hogql_context:
            hogql_context = Database.create_for(team_id=self.context["team_id"])

        if schema.table and schema.table.deleted:
            return None

        return SimpleTableSerializer(schema.table, context={"database": hogql_context}).data or None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_sync_frequency(self, schema: ExternalDataSchema):
        return sync_frequency_interval_to_sync_frequency(schema.sync_frequency_interval)

    @extend_schema_field(serializers.TimeField(allow_null=True))
    def get_sync_time_of_day(self, schema: ExternalDataSchema):
        return schema.sync_time_of_day

    @extend_schema_field(serializers.ChoiceField(choices=["consolidated", "cdc_only", "both"]))
    def get_cdc_table_mode(self, schema: ExternalDataSchema) -> str:
        return schema.cdc_table_mode

    def _run_temporal_side_effect(self, callback: Callable[[], None]) -> None:
        post_commit_actions = self.context.get("post_commit_actions")
        if isinstance(post_commit_actions, list):
            post_commit_actions.append(callback)
            return

        callback()

    def update(self, instance: ExternalDataSchema, validated_data: dict[str, Any]) -> ExternalDataSchema:
        data = self.initial_data if isinstance(self.initial_data, dict) else {}

        sync_type = data.get("sync_type")

        if (
            sync_type is not None
            and sync_type != ExternalDataSchema.SyncType.FULL_REFRESH
            and sync_type != ExternalDataSchema.SyncType.INCREMENTAL
            and sync_type != ExternalDataSchema.SyncType.APPEND
            and sync_type != ExternalDataSchema.SyncType.WEBHOOK
            and sync_type != ExternalDataSchema.SyncType.CDC
        ):
            raise ValidationError("Invalid sync type")

        if sync_type == ExternalDataSchema.SyncType.CDC:
            from posthog.models import Team

            team = Team.objects.get(id=self.context["team_id"])
            if not is_cdc_enabled_for_team(team):
                raise ValidationError("CDC is not enabled for this team")

        # Only update sync_type if it was explicitly provided in the request
        if "sync_type" in data:
            validated_data["sync_type"] = sync_type

        trigger_refresh = False
        # Update the validated_data with incremental fields
        if sync_type in (
            ExternalDataSchema.SyncType.INCREMENTAL,
            ExternalDataSchema.SyncType.APPEND,
            ExternalDataSchema.SyncType.WEBHOOK,
        ):
            payload = instance.sync_type_config

            if "primary_key_columns" in data:
                new_pk = data.get("primary_key_columns")
                old_pk = instance.sync_type_config.get("primary_key_columns")
                if (
                    sync_type == ExternalDataSchema.SyncType.INCREMENTAL
                    and new_pk != old_pk
                    and instance.table is not None
                ):
                    raise ValidationError(
                        "Primary key cannot be changed after data has been synced. "
                        "Delete the synced data first, then change the primary key."
                    )
                payload["primary_key_columns"] = new_pk

            # Detect incremental field changes before mutating payload
            incremental_field_changed = False
            incremental_field = data.get("incremental_field")
            if sync_type in (ExternalDataSchema.SyncType.INCREMENTAL, ExternalDataSchema.SyncType.APPEND):
                incremental_field_changed = (
                    payload.get("incremental_field") != incremental_field
                    or payload.get("incremental_field_last_value") is None
                )

            if "incremental_field" in data:
                payload["incremental_field"] = incremental_field
            if "incremental_field_type" in data:
                payload["incremental_field_type"] = data.get("incremental_field_type")

            if incremental_field_changed:
                if instance.table is not None and isinstance(incremental_field, str):
                    # Get the max_value and set it on incremental_field_last_value
                    max_value = instance.table.get_max_value_for_column(incremental_field)
                    if max_value:
                        instance.update_incremental_field_value(max_value, save=False)
                    else:
                        # if we can't get the max value, reset the table
                        payload["incremental_field_last_value"] = None
                        trigger_refresh = True

            validated_data["sync_type_config"] = payload
        elif sync_type == ExternalDataSchema.SyncType.CDC:
            payload = instance.sync_type_config
            if payload.get("cdc_mode") is None:
                payload["cdc_mode"] = "snapshot"
            cdc_table_mode = data.get("cdc_table_mode")
            if cdc_table_mode in ("consolidated", "cdc_only", "both"):
                payload["cdc_table_mode"] = cdc_table_mode
            validated_data["sync_type_config"] = payload
        else:
            # For CDC schemas where sync_type isn't being changed, still allow cdc_table_mode updates
            if instance.sync_type == ExternalDataSchema.SyncType.CDC and "cdc_table_mode" in data:
                cdc_table_mode = data.get("cdc_table_mode")
                if cdc_table_mode in ("consolidated", "cdc_only", "both"):
                    payload = instance.sync_type_config
                    payload["cdc_table_mode"] = cdc_table_mode
                    validated_data["sync_type_config"] = payload

        should_sync = validated_data.get("should_sync", None)
        sync_frequency = data.get("sync_frequency", None)
        sync_time_of_day_in_payload = "sync_time_of_day" in data
        sync_time_of_day = data.get("sync_time_of_day", None)
        was_sync_frequency_updated = False
        was_sync_time_of_day_updated = False
        source = instance.source

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
        else:
            if sync_time_of_day_in_payload and sync_time_of_day != instance.sync_time_of_day:
                was_sync_time_of_day_updated = True
                validated_data["sync_time_of_day"] = None
                instance.sync_time_of_day = None

        if source.supports_scheduled_sync and should_sync is True and sync_type is None and instance.sync_type is None:
            raise ValidationError("Sync type must be set up first before enabling schema")

        # When re-enabling a webhook schema, force a full refresh to avoid missing data
        if (
            should_sync is True
            and instance.should_sync is False
            and instance.is_webhook
            and instance.initial_sync_complete
        ):
            validated_data.setdefault("sync_type_config", instance.sync_type_config)
            validated_data["sync_type_config"]["reset_pipeline"] = True
            trigger_refresh = True

        if source.is_direct_postgres:
            # We use "should_sync" to determine if the table should be exposed or hidden.
            if should_sync is True and instance.should_sync is False:
                source_catalog, source_schema, source_table_name = get_direct_postgres_location(
                    schema_name=instance.name,
                    schema_metadata=instance.schema_metadata,
                    default_schema=(source.job_inputs or {}).get("schema"),
                )
                validated_data["table"] = upsert_direct_postgres_table(
                    instance.table,
                    schema_name=instance.name,
                    source=source,
                    columns=postgres_schema_metadata_to_dwh_columns(instance.schema_metadata),
                    source_catalog=source_catalog,
                    source_schema=source_schema,
                    source_table_name=source_table_name,
                )

            if should_sync is False and instance.should_sync is True:
                hide_direct_postgres_table(instance.table)

        # CDC publication management: add/remove table when toggling should_sync
        is_cdc = (sync_type == ExternalDataSchema.SyncType.CDC) or (
            sync_type is None and instance.sync_type == ExternalDataSchema.SyncType.CDC
        )
        if is_cdc and source.source_type == ExternalDataSourceType.POSTGRES:
            self._handle_cdc_publication_change(instance, source, should_sync, sync_type)

        if trigger_refresh:
            instance.sync_type_config.update({"reset_pipeline": True})
            validated_data["sync_type_config"].update({"reset_pipeline": True})

        updated_instance = super().update(instance, validated_data)

        if source.supports_scheduled_sync and (
            should_sync is not None or was_sync_frequency_updated or was_sync_time_of_day_updated
        ):

            def update_schedule() -> None:
                should_sync_value = should_sync if should_sync is not None else updated_instance.should_sync
                schedule_exists = external_data_workflow_exists(str(updated_instance.id))

                if schedule_exists:
                    if should_sync is False:
                        pause_external_data_schedule(str(updated_instance.id))
                    elif should_sync is True:
                        unpause_external_data_schedule(str(updated_instance.id))
                elif should_sync is True:
                    sync_external_data_job_workflow(updated_instance, create=True, should_sync=should_sync_value)

                if was_sync_frequency_updated or was_sync_time_of_day_updated:
                    sync_external_data_job_workflow(updated_instance, create=False, should_sync=should_sync_value)

            self._run_temporal_side_effect(update_schedule)

        if trigger_refresh:
            self._run_temporal_side_effect(lambda: trigger_external_data_workflow(updated_instance))

        if sync_type == ExternalDataSchema.SyncType.WEBHOOK:
            self._maybe_create_webhook(updated_instance)

        # Sync CDC extraction schedule after any CDC schema change
        if is_cdc:

            def sync_cdc_schedule() -> None:
                try:
                    sync_cdc_extraction_schedule(source)
                except Exception as e:
                    logger.exception("Failed to sync CDC extraction schedule", exc_info=e)

            self._run_temporal_side_effect(sync_cdc_schedule)

        return updated_instance

    def _maybe_create_webhook(self, schema: ExternalDataSchema) -> None:
        source = schema.source
        if not source.job_inputs:
            return

        try:
            source_type = ExternalDataSourceType(source.source_type)
            source_impl = SourceRegistry.get_source(source_type)
        except Exception as e:
            capture_exception(e)
            return

        if not isinstance(source_impl, WebhookSource):
            return

        config = source_impl.parse_config(source.job_inputs)
        source_schemas = source_impl.get_schemas(config, schema.team_id)
        webhook_source_schemas = {s.name for s in source_schemas if s.supports_webhooks}

        if schema.name not in webhook_source_schemas:
            return

        try:
            hog_fn_result = get_or_create_webhook_hog_function(
                team=schema.team,
                source=source_impl,
                source_id=str(source.pk),
                eligible_schemas=[schema],
            )

            if hog_fn_result.error or not hog_fn_result.hog_function:
                raise ValidationError(
                    f"Failed to set up webhook: {hog_fn_result.error or 'Unknown error'}. "
                    "You can set up the webhook manually from the Webhook tab."
                )

            if hog_fn_result.hog_function_created:
                # Only register the webhook if we're creating the hog function when it didn't exist previously
                result = create_and_register_webhook(source_impl, config, hog_fn_result, schema.team_id)
                if not result.success:
                    raise ValidationError(
                        f"Failed to register webhook on your source: {result.error or 'Unknown error'}. "
                        "You can set up the webhook manually from the Webhook tab."
                    )
        except ValidationError:
            raise
        except Exception as e:
            logger.exception("Failed to create webhook during schema update", error=str(e))
            raise ValidationError(
                "Failed to create webhook. You can set up the webhook manually from the Webhook tab."
            ) from e

    def _handle_cdc_publication_change(
        self,
        instance: ExternalDataSchema,
        source: ExternalDataSource,
        should_sync: bool | None,
        sync_type: str | None,
    ) -> None:
        """Manage CDC publication tables when a schema is toggled or newly set to CDC."""
        cdc_config = PostgresCDCConfig.from_source(source)
        if cdc_config.management_mode != "posthog" or not cdc_config.publication_name:
            return

        pub_name = cdc_config.publication_name
        _, db_schema, source_table_name = get_direct_postgres_location(
            schema_name=instance.name,
            schema_metadata=instance.schema_metadata,
            default_schema=(source.job_inputs or {}).get("schema"),
        )

        newly_set_to_cdc = (
            sync_type == ExternalDataSchema.SyncType.CDC and instance.sync_type != ExternalDataSchema.SyncType.CDC
        )

        # Add table to publication when enabling CDC or toggling sync on
        if newly_set_to_cdc or (should_sync is True and not instance.should_sync):
            self._alter_cdc_publication(source, pub_name, db_schema, source_table_name, action="add")

            # Always force a full re-snapshot on re-enable: while removed from the
            # publication the replication slot kept advancing, so any changes made
            # during that window are permanently lost regardless of how short it was.
            if should_sync is True and not newly_set_to_cdc:
                instance.sync_type_config["cdc_mode"] = "snapshot"
                instance.initial_sync_complete = False
                instance.save(update_fields=["sync_type_config", "initial_sync_complete", "updated_at"])

        # Remove table from publication when toggling sync off
        elif should_sync is False and instance.should_sync:
            self._alter_cdc_publication(source, pub_name, db_schema, source_table_name, action="remove")

    def _alter_cdc_publication(
        self,
        source: ExternalDataSource,
        pub_name: str,
        db_schema: str,
        table_name: str,
        action: str,
    ) -> None:
        """Best-effort add/remove a table from the CDC publication."""
        from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import (
            add_table_to_publication,
            cdc_pg_connection,
            remove_table_from_publication,
        )

        try:
            with cdc_pg_connection(source) as conn:
                if action == "add":
                    add_table_to_publication(conn, pub_name, db_schema, table_name)
                else:
                    remove_table_from_publication(conn, pub_name, db_schema, table_name)
        except Exception as e:
            logger.exception(
                "Failed to alter CDC publication",
                action=action,
                table=table_name,
                pub_name=pub_name,
                error=str(e),
            )


class SimpleExternalDataSchemaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalDataSchema
        fields = ["id", "name", "label", "should_sync", "last_synced_at", "sync_type"]


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

        if instance.is_cdc:
            # Reset CDC state so the next run does a full re-snapshot
            instance.sync_type_config["cdc_mode"] = "snapshot"
            instance.sync_type_config.pop("cdc_last_log_position", None)
            instance.sync_type_config.pop("cdc_deferred_runs", None)
            instance.initial_sync_complete = False

        # Save BEFORE triggering the workflow so the Postgres source sees
        # cdc_mode="snapshot" when it reloads the schema from DB.
        # Otherwise a race: the workflow starts, loads stale "streaming" mode,
        # raises CDCHandledExternally, and the full-refresh never runs.
        instance.status = ExternalDataSchema.Status.RUNNING
        instance.save()

        try:
            trigger_external_data_workflow(instance)
        except temporalio.service.RPCError as e:
            logger.exception(f"Could not trigger external data job for schema {instance.id}", exc_info=e)

        return Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    def cancel(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()

        latest_running_job = (
            ExternalDataJob.objects.filter(schema_id=instance.pk, team_id=instance.team_id)
            .order_by("-created_at")
            .first()
        )

        if not latest_running_job or latest_running_job.status != "Running" or not latest_running_job.workflow_id:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"detail": "No running sync to cancel."},
            )

        try:
            cancel_external_data_workflow(latest_running_job.workflow_id)
        except temporalio.service.RPCError as e:
            logger.exception(f"Could not cancel external data workflow for schema {instance.id}", exc_info=e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"detail": "Could not find workflow to cancel. The sync may have already finished."},
            )

        return Response(status=status.HTTP_200_OK)

    @action(methods=["DELETE"], detail=True)
    def delete_data(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()

        if instance.source.is_direct_postgres:
            hide_direct_postgres_table(instance.table)
            instance.should_sync = False
            instance.save(update_fields=["should_sync", "updated_at"])
            return Response(status=status.HTTP_200_OK)

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

        credentials_valid, credentials_error = new_source.validate_credentials(config, self.team_id, instance.name)
        if not credentials_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": credentials_error or "Invalid credentials"},
            )

        try:
            schemas = new_source.get_schemas(config, self.team_id, names=[instance.name])
        except Exception as e:
            capture_exception(e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": str(e)},
            )

        if not schemas:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"message": f"Schema with name {instance.name} not found"}
            )

        schema = schemas[0]

        data = {
            "incremental_fields": schema.incremental_fields,
            "incremental_available": schema.supports_incremental,
            "append_available": schema.supports_append,
            "cdc_available": schema.supports_cdc if is_cdc_enabled_for_team(self.team) else None,
            "full_refresh_available": True,
            "supports_webhooks": schema.supports_webhooks,
            "available_columns": [
                {"field": col_name, "label": col_name, "type": col_type, "nullable": nullable}
                for col_name, col_type, nullable in schema.columns
            ],
            "detected_primary_keys": schema.detected_primary_keys,
        }

        return Response(status=status.HTTP_200_OK, data=data)


@dataclasses.dataclass(frozen=True)
class ExternalDataSchemaContext(ActivityContextBase):
    name: str
    sync_type: str | None
    sync_frequency: str | None
    source_id: str
    source_type: str


@mutable_receiver(model_activity_signal, sender=ExternalDataSchema)
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
        from products.data_warehouse.backend.models.external_data_schema import (
            sync_frequency_interval_to_sync_frequency,
        )

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
