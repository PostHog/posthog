import uuid
import dataclasses
from typing import Any

from django.db.models import Prefetch, Q
from django.dispatch import receiver

import structlog
import temporalio
from dateutil import parser
from rest_framework import filters, serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql.database.database import Database

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.activity_logging.external_data_utils import (
    get_external_data_source_created_by_info,
    get_external_data_source_detail_name,
)
from posthog.models.signals import model_activity_signal
from posthog.models.user import User
from posthog.temporal.data_imports.sources import SourceRegistry
from posthog.temporal.data_imports.sources.common.config import Config
from posthog.warehouse.api.external_data_schema import ExternalDataSchemaSerializer, SimpleExternalDataSchemaSerializer
from posthog.warehouse.data_load.service import (
    cancel_external_data_workflow,
    delete_external_data_schedule,
    is_any_external_data_schema_paused,
    sync_external_data_job_workflow,
    trigger_external_data_source_workflow,
)
from posthog.warehouse.models import (
    DataWarehouseManagedViewSet,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)
from posthog.warehouse.models.revenue_analytics_config import ExternalDataSourceRevenueAnalyticsConfig
from posthog.warehouse.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)


class ExternalDataSourceRevenueAnalyticsConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalDataSourceRevenueAnalyticsConfig
        fields = ["enabled", "include_invoiceless_charges"]


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


class ExternalDataSourceSerializers(serializers.ModelSerializer):
    account_id = serializers.CharField(write_only=True)
    client_secret = serializers.CharField(write_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)
    created_by = serializers.SerializerMethodField(read_only=True)
    latest_error = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    schemas = serializers.SerializerMethodField(read_only=True)
    revenue_analytics_config = ExternalDataSourceRevenueAnalyticsConfigSerializer(
        source="revenue_analytics_config_safe", read_only=True
    )

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
            "revenue_analytics_config",
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
            "revenue_analytics_config",
        ]

    """
    This method is used to remove sensitive fields from the response.
    IMPORTANT: This method should be updated when a new source type is added to allow for editing of the new source.
    """

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        # non-sensitive fields
        job_inputs_allowed_keys = {
            # stripe
            "stripe_account_id",
            # sql
            "database",
            "host",
            "port",
            "user",
            "schema",
            "ssh_tunnel",
            "using_ssl",
            # vitally
            "region"
            # chargebee
            "site_name",
            # zendesk
            "subdomain",
            "email_address",
            # hubspot
            "hubspot_integration_id",
            # snowflake
            "account_id",
            "warehouse",
            "role",
            # bigquery
            "dataset_id",
            "temporary_dataset",
            "dataset_project"
            # google ads
            "customer_id",
            "google_ads_integration_id",
            "is_mcc_account",
            # google sheets
            "spreadsheet_url",
            # linkedin ads
            "linkedin_ads_integration_id",
            # meta ads
            "meta_ads_integration_id",
            # reddit ads
            "reddit_integration_id",
            # salesforce
            "salesforce_integration_id",
            # shopify
            "shopify_store_id",
            # temporal
            "namespace",
        }
        job_inputs = representation.get("job_inputs", {})
        if isinstance(job_inputs, dict):
            # Reconstruct ssh_tunnel (if needed) structure for UI handling
            if "ssh_tunnel" in job_inputs and isinstance(job_inputs["ssh_tunnel"], dict):
                existing_ssh_tunnel: dict = job_inputs["ssh_tunnel"]
                existing_auth: dict = existing_ssh_tunnel.get("auth", {})
                ssh_tunnel = {
                    "enabled": existing_ssh_tunnel.get("enabled", False),
                    "host": existing_ssh_tunnel.get("host", None),
                    "port": existing_ssh_tunnel.get("port", None),
                    "auth": {
                        "selection": existing_auth.get("type", None),
                        "username": existing_auth.get("username", None),
                        "password": None,
                        "passphrase": None,
                        "private_key": None,
                    },
                }
                job_inputs["ssh_tunnel"] = ssh_tunnel

            # Remove sensitive fields
            for key in list(job_inputs.keys()):  # Use list() to avoid modifying dict during iteration
                if key not in job_inputs_allowed_keys:
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

        source_type_model = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type_model)

        if existing_job_inputs:
            new_job_inputs = {**existing_job_inputs, **validated_data.get("job_inputs", {})}
        else:
            new_job_inputs = validated_data.get("job_inputs", {})

        is_valid, errors = source.validate_config(new_job_inputs)
        if not is_valid:
            raise ValidationError(f"Invalid source config: {', '.join(errors)}")

        source_config: Config = source.parse_config(new_job_inputs)
        validated_data["job_inputs"] = source_config.to_dict()

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

        source_type_model = ExternalDataSourceType(source_type)
        source = SourceRegistry.get_source(source_type_model)
        is_valid, errors = source.validate_config(payload)
        if not is_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid source config: {', '.join(errors)}"},
            )
        source_config: Config = source.parse_config(payload)

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
        )

        source_schemas = source.get_schemas(source_config, self.team_id)
        schema_names = [schema.name for schema in source_schemas]

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

        # Create all ExternalDataSchema objects and enable syncing for active schemas
        for schema in payload_schemas:
            sync_type = schema.get("sync_type")
            requires_incremental_fields = sync_type == "incremental" or sync_type == "append"
            incremental_field = schema.get("incremental_field")
            incremental_field_type = schema.get("incremental_field_type")
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

            schema_model = ExternalDataSchema.objects.create(
                name=schema.get("name"),
                team=self.team,
                source=new_source_model,
                should_sync=should_sync,
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

            if should_sync:
                active_schemas.append(schema_model)

        try:
            for active_schema in active_schemas:
                sync_external_data_job_workflow(active_schema, create=True, should_sync=active_schema.should_sync)
        except Exception as e:
            # Log error but don't fail because the source model was already created
            logger.exception("Could not trigger external data job", exc_info=e)

        if new_source_model.revenue_analytics_config_safe.enabled:
            managed_viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
                team=self.team,
                kind=DataWarehouseManagedViewSet.Kind.REVENUE_ANALYTICS,
            )
            managed_viewset.sync_views()

        return Response(status=status.HTTP_201_CREATED, data={"id": new_source_model.pk})

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
            .filter(team_id=self.team_id, source_id=instance.id)
            .select_related("table")
            .all()
        ):
            # Delete temporal schedule
            delete_external_data_schedule(str(schema.id))

            # Delete data from S3 if it exists
            schema.delete_table()
            # Soft delete postgres models
            schema.soft_delete()

        # Delete the old source schedule if it still exists
        delete_external_data_schedule(str(instance.id))

        # Soft delete the source model
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

        source_type_model = ExternalDataSourceType(source_type)
        source = SourceRegistry.get_source(source_type_model)
        is_valid, errors = source.validate_config(request.data)
        if not is_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid source config: {', '.join(errors)}"},
            )
        source_config: Config = source.parse_config(request.data)

        credentials_valid, credentials_error = source.validate_credentials(source_config, self.team_id)
        if not credentials_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": credentials_error or "Invalid credentials"},
            )

        try:
            schemas = source.get_schemas(source_config, self.team_id, True)
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
                "incremental_field": schema.incremental_fields[0]["field"]
                if len(schema.incremental_fields) > 0 and len(schema.incremental_fields[0]["field"]) > 0
                else None,
                "sync_type": None,
                "rows": schema.row_count,
            }
            for schema in schemas
        ]
        return Response(status=status.HTTP_200_OK, data=data)

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
        sources = SourceRegistry.get_all_sources()
        configs = {name: source.get_source_config for name, source in sources.items()}

        return Response(
            status=status.HTTP_200_OK,
            data={str(key): value.model_dump() for key, value in configs.items()},
        )

    @action(methods=["PATCH"], detail=True)
    def revenue_analytics_config(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Update the revenue analytics configuration and return the full external data source."""
        external_data_source = self.get_object()
        config = external_data_source.revenue_analytics_config_safe

        config_serializer = ExternalDataSourceRevenueAnalyticsConfigSerializer(config, data=request.data, partial=True)
        config_serializer.is_valid(raise_exception=True)
        config_serializer.save()

        if config.enabled:
            managed_viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
                team=self.team,
                kind=DataWarehouseManagedViewSet.Kind.REVENUE_ANALYTICS,
            )
            managed_viewset.sync_views()
        else:
            try:
                managed_viewset = DataWarehouseManagedViewSet.objects.get(
                    team=self.team,
                    kind=DataWarehouseManagedViewSet.Kind.REVENUE_ANALYTICS,
                )
                managed_viewset.delete_with_views()

            except DataWarehouseManagedViewSet.DoesNotExist:
                pass

        # Return the full external data source with updated config
        source_serializer = self.get_serializer(external_data_source, context=self.get_serializer_context())
        return Response(source_serializer.data)


@dataclasses.dataclass(frozen=True)
class ExternalDataSourceContext(ActivityContextBase):
    source_type: str
    prefix: str | None
    created_by_user_id: str | None
    created_by_user_email: str | None
    created_by_user_name: str | None


@receiver(model_activity_signal, sender=ExternalDataSource)
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
