import uuid
from typing import Any

import structlog
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import User
from posthog.permissions import OrganizationMemberPermissions
from posthog.warehouse.data_load.service import (
    sync_external_data_job_workflow,
    trigger_external_data_workflow,
    delete_external_data_schedule,
    cancel_external_data_workflow,
    delete_data_import_folder,
    is_any_external_data_job_paused,
)
from posthog.warehouse.models import ExternalDataSource, ExternalDataSchema, ExternalDataJob
from posthog.warehouse.api.external_data_schema import ExternalDataSchemaSerializer
from posthog.temporal.data_imports.pipelines.schemas import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from posthog.temporal.data_imports.pipelines.hubspot.auth import (
    get_access_token_from_code,
)
import temporalio

logger = structlog.get_logger(__name__)


class ExternalDataSourceSerializers(serializers.ModelSerializer):
    account_id = serializers.CharField(write_only=True)
    client_secret = serializers.CharField(write_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)
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
        read_only_fields = ["id", "created_by", "created_at", "status", "source_type", "last_run_at", "schemas"]

    def get_last_run_at(self, instance: ExternalDataSource) -> str:
        latest_completed_run = (
            ExternalDataJob.objects.filter(pipeline_id=instance.pk, status="Completed", team_id=instance.team_id)
            .order_by("-created_at")
            .first()
        )

        return latest_completed_run.created_at if latest_completed_run else None

    def get_schemas(self, instance: ExternalDataSource):
        schemas = instance.schemas.order_by("name").all()
        return ExternalDataSchemaSerializer(schemas, many=True, read_only=True).data


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


class ExternalDataSourceViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete External data Sources.
    """

    queryset = ExternalDataSource.objects.all()
    serializer_class = ExternalDataSourceSerializers
    permission_classes = [IsAuthenticated, OrganizationMemberPermissions]
    filter_backends = [filters.SearchFilter]
    search_fields = ["source_id"]
    ordering = "-created_at"

    def get_queryset(self):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        if self.action == "list":
            return (
                self.queryset.filter(team_id=self.team_id)
                .prefetch_related("created_by", "schemas")
                .order_by(self.ordering)
            )

        return (
            self.queryset.filter(team_id=self.team_id).prefetch_related("created_by", "schemas").order_by(self.ordering)
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

        if is_any_external_data_job_paused(self.team_id):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please contact PostHog support to increase your limit."},
            )

        # TODO: remove dummy vars
        if source_type == ExternalDataSource.Type.STRIPE:
            new_source_model = self._handle_stripe_source(request, *args, **kwargs)
        elif source_type == ExternalDataSource.Type.HUBSPOT:
            new_source_model = self._handle_hubspot_source(request, *args, **kwargs)
        else:
            raise NotImplementedError(f"Source type {source_type} not implemented")

        schemas = PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[source_type]
        for schema in schemas:
            ExternalDataSchema.objects.create(
                name=schema,
                team=self.team,
                source=new_source_model,
            )

        try:
            sync_external_data_job_workflow(new_source_model, create=True)
        except Exception as e:
            # Log error but don't fail because the source model was already created
            logger.exception("Could not trigger external data job", exc_info=e)

        return Response(status=status.HTTP_201_CREATED, data={"id": new_source_model.pk})

    def _handle_stripe_source(self, request: Request, *args: Any, **kwargs: Any) -> ExternalDataSource:
        payload = request.data["payload"]
        client_secret = payload.get("client_secret")
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
                "stripe_secret_key": client_secret,
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

        access_token, refresh_token = get_access_token_from_code(code, redirect_uri=redirect_uri)

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

    def prefix_required(self, source_type: str) -> bool:
        source_type_exists = ExternalDataSource.objects.filter(team_id=self.team.pk, source_type=source_type).exists()
        return source_type_exists

    def prefix_exists(self, source_type: str, prefix: str) -> bool:
        prefix_exists = ExternalDataSource.objects.filter(
            team_id=self.team.pk, source_type=source_type, prefix=prefix
        ).exists()
        return prefix_exists

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()

        latest_running_job = (
            ExternalDataJob.objects.filter(pipeline_id=instance.pk, team_id=instance.team_id)
            .order_by("-created_at")
            .first()
        )
        if latest_running_job and latest_running_job.workflow_id and latest_running_job.status == "Running":
            cancel_external_data_workflow(latest_running_job.workflow_id)

        latest_completed_job = (
            ExternalDataJob.objects.filter(pipeline_id=instance.pk, team_id=instance.team_id, status="Completed")
            .order_by("-created_at")
            .first()
        )
        if latest_completed_job:
            try:
                delete_data_import_folder(latest_completed_job.folder_path)
            except Exception as e:
                logger.exception(
                    f"Could not clean up data import folder: {latest_completed_job.folder_path}", exc_info=e
                )
                pass

        delete_external_data_schedule(instance)
        return super().destroy(request, *args, **kwargs)

    @action(methods=["POST"], detail=True)
    def reload(self, request: Request, *args: Any, **kwargs: Any):
        instance = self.get_object()

        if is_any_external_data_job_paused(self.team_id):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please contact PostHog support to increase your limit."},
            )

        try:
            trigger_external_data_workflow(instance)

        except temporalio.service.RPCError as e:
            # schedule doesn't exist
            if e.message == "sql: no rows in result set":
                sync_external_data_job_workflow(instance, create=True)
        except Exception as e:
            logger.exception("Could not trigger external data job", exc_info=e)
            raise

        instance.status = "Running"
        instance.save()
        return Response(status=status.HTTP_200_OK)
