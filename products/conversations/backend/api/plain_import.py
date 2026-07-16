"""Plain historical import API for Conversations settings."""

from __future__ import annotations

import asyncio

from django.utils import timezone

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import (
    serializers,
    status as drf_status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.conversations.backend.models import EmailChannel, PlainImportJob
from products.conversations.backend.permissions import IsConversationsAdmin
from products.conversations.backend.temporal.plain_import.client import PlainCredentials, validate_plain_credentials
from products.conversations.backend.temporal.plain_import.constants import REGION_HOSTS
from products.conversations.backend.temporal.plain_import.starter import start_plain_import_workflow

logger = structlog.get_logger(__name__)

WORKFLOW_START_FAILED_MESSAGE = "Failed to start the import. Please try again or contact support if it persists."


class PlainImportStartSerializer(serializers.Serializer):
    api_key = serializers.CharField(
        help_text="Plain API key with thread:read, timeline:read, and customer:read scopes.",
        write_only=True,
        max_length=500,
    )
    region = serializers.ChoiceField(
        choices=[(key, key.upper()) for key in REGION_HOSTS],
        help_text="Plain API region: 'uk' (core-api.uk.plain.com) or 'us' (core-api.us.plain.com).",
    )
    default_email_channel_id = serializers.UUIDField(
        help_text=(
            "Optional fallback email channel for email-sourced Plain threads. "
            "Omit or null to leave those tickets without an email channel."
        ),
        required=False,
        allow_null=True,
    )


class PlainImportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Human-readable error message.")


class PlainImportJobSerializer(serializers.ModelSerializer):
    region = serializers.SerializerMethodField(help_text="Plain API region used for this import job.")
    has_credentials = serializers.SerializerMethodField(
        help_text="Whether stored Plain credentials exist for this job (the API key is never returned)."
    )

    class Meta:
        model = PlainImportJob
        fields = [
            "id",
            "status",
            "region",
            "has_credentials",
            "total_tickets",
            "processed_tickets",
            "imported_tickets",
            "skipped_tickets",
            "failed_tickets",
            "started_at",
            "finished_at",
            "latest_error",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Unique identifier for the import job."},
            "status": {"help_text": "Current job state: pending, running, completed, or failed."},
            "total_tickets": {"help_text": "Total number of threads discovered for import."},
            "processed_tickets": {"help_text": "Number of threads processed so far."},
            "imported_tickets": {"help_text": "Number of threads successfully imported."},
            "skipped_tickets": {"help_text": "Number of threads skipped because they were already imported."},
            "failed_tickets": {"help_text": "Number of threads that failed to import."},
            "started_at": {"help_text": "When the import started running."},
            "finished_at": {"help_text": "When the import reached a terminal state."},
            "latest_error": {"help_text": "Generic, user-safe error message when the job failed."},
            "created_at": {"help_text": "When the import job was created."},
            "updated_at": {"help_text": "When the import job was last updated."},
        }

    def get_region(self, obj: PlainImportJob) -> str | None:
        return (obj.job_inputs or {}).get("region")

    def get_has_credentials(self, obj: PlainImportJob) -> bool:
        return bool((obj.job_inputs or {}).get("api_key"))


class PlainImportViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = PlainImportJobSerializer
    permission_classes = [IsConversationsAdmin]
    queryset = PlainImportJob.objects.unscoped()

    def safely_get_queryset(self, queryset):
        return PlainImportJob.objects.all().order_by("-created_at")

    @extend_schema(
        request=PlainImportStartSerializer,
        responses={
            201: PlainImportJobSerializer,
            400: PlainImportErrorSerializer,
            500: PlainImportErrorSerializer,
        },
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        team_id = self.team_id
        if not self.team.conversations_enabled:
            return Response(
                {"detail": "Conversations is not enabled for this team"}, status=drf_status.HTTP_400_BAD_REQUEST
            )

        serializer = PlainImportStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        running = PlainImportJob.objects.filter(
            status__in=[PlainImportJob.Status.PENDING, PlainImportJob.Status.RUNNING],
        ).exists()
        if running:
            return Response(
                {"detail": "A Plain import is already running for this team"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        default_email_channel_id = data.get("default_email_channel_id")
        if (
            default_email_channel_id is not None
            and not EmailChannel.objects.filter(team_id=team_id, id=default_email_channel_id).exists()
        ):
            return Response(
                {"detail": "The selected default email channel does not belong to this team"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        credentials = PlainCredentials(
            api_key=data["api_key"],
            region=data["region"],
        )
        if not validate_plain_credentials(credentials):
            return Response({"detail": "Plain rejected the credentials"}, status=drf_status.HTTP_400_BAD_REQUEST)

        job = PlainImportJob.objects.create(
            team_id=team_id,
            status=PlainImportJob.Status.PENDING,
            job_inputs={
                "api_key": credentials.api_key,
                "region": credentials.region,
            },
        )

        try:
            workflow_id, workflow_run_id = asyncio.run(
                start_plain_import_workflow(
                    job_id=str(job.id),
                    team_id=team_id,
                    default_email_channel_id=(
                        str(default_email_channel_id) if default_email_channel_id is not None else None
                    ),
                )
            )
            job.workflow_id = workflow_id
            job.workflow_run_id = workflow_run_id
            job.status = PlainImportJob.Status.RUNNING
            job.started_at = timezone.now()
            job.save(update_fields=["workflow_id", "workflow_run_id", "status", "started_at", "updated_at"])
        except Exception:
            logger.exception("plain_import_workflow_start_failed", job_id=str(job.id), team_id=team_id)
            job.status = PlainImportJob.Status.FAILED
            job.latest_error = WORKFLOW_START_FAILED_MESSAGE
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "latest_error", "finished_at", "updated_at"])
            return Response({"detail": WORKFLOW_START_FAILED_MESSAGE}, status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(PlainImportJobSerializer(job).data, status=drf_status.HTTP_201_CREATED)

    @extend_schema(
        responses={
            200: PlainImportJobSerializer,
            404: PlainImportErrorSerializer,
        },
    )
    @action(detail=False, methods=["get"])
    def status(self, request: Request, *args, **kwargs) -> Response:
        job = PlainImportJob.objects.order_by("-created_at").first()
        if job is None:
            return Response({"detail": "No Plain import job found"}, status=drf_status.HTTP_404_NOT_FOUND)

        return Response(PlainImportJobSerializer(job).data)
