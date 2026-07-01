"""Zendesk historical import API for Conversations settings."""

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
from posthog.permissions import OrganizationAdminReadPermissions

from products.conversations.backend.models import ZendeskImportJob
from products.conversations.backend.temporal.zendesk_import.client import (
    ZendeskCredentials,
    validate_zendesk_credentials,
)
from products.conversations.backend.temporal.zendesk_import.starter import start_zendesk_import_workflow

logger = structlog.get_logger(__name__)

# Generic, user-safe message stored in `latest_error` and returned to admins. Raw
# exception strings can carry internal hostnames, query details, or secrets from
# failing requests, so the real error is logged server-side instead.
WORKFLOW_START_FAILED_MESSAGE = "Failed to start the import. Please try again or contact support if it persists."


class ZendeskImportStartSerializer(serializers.Serializer):
    subdomain = serializers.CharField(
        help_text="Zendesk subdomain (e.g. 'acme' from acme.zendesk.com).",
        max_length=255,
    )
    email_address = serializers.EmailField(help_text="Zendesk agent email tied to the API token.")
    api_token = serializers.CharField(
        help_text="Zendesk API token with ticket read access.",
        write_only=True,
        max_length=500,
    )


class ZendeskImportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Human-readable error message.")


class ZendeskImportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ZendeskImportJob
        fields = [
            "id",
            "status",
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
            "total_tickets": {"help_text": "Total number of tickets discovered for import."},
            "processed_tickets": {"help_text": "Number of tickets processed so far."},
            "imported_tickets": {"help_text": "Number of tickets successfully imported."},
            "skipped_tickets": {"help_text": "Number of tickets skipped because they were already imported."},
            "failed_tickets": {"help_text": "Number of tickets that failed to import."},
            "started_at": {"help_text": "When the import started running."},
            "finished_at": {"help_text": "When the import reached a terminal state."},
            "latest_error": {"help_text": "Generic, user-safe error message when the job failed."},
            "created_at": {"help_text": "When the import job was created."},
            "updated_at": {"help_text": "When the import job was last updated."},
        }


class ZendeskImportViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    # Settings-only, admin-gated, session-auth endpoint — not exposed as a public API scope.
    scope_object = "INTERNAL"
    serializer_class = ZendeskImportJobSerializer
    permission_classes = [OrganizationAdminReadPermissions]
    queryset = ZendeskImportJob.objects.unscoped()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).order_by("-created_at")

    @extend_schema(
        request=ZendeskImportStartSerializer,
        responses={
            201: ZendeskImportJobSerializer,
            400: ZendeskImportErrorSerializer,
            500: ZendeskImportErrorSerializer,
        },
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        team_id = self.team_id
        if not self.team.conversations_enabled:
            return Response(
                {"detail": "Conversations is not enabled for this team"}, status=drf_status.HTTP_400_BAD_REQUEST
            )

        serializer = ZendeskImportStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        credentials = ZendeskCredentials(
            subdomain=data["subdomain"],
            email_address=data["email_address"],
            api_token=data["api_token"],
        )
        if not validate_zendesk_credentials(credentials):
            return Response({"detail": "Zendesk rejected the credentials"}, status=drf_status.HTTP_400_BAD_REQUEST)

        running = (
            ZendeskImportJob.objects.unscoped()
            .filter(
                team_id=team_id,
                status__in=[ZendeskImportJob.Status.PENDING, ZendeskImportJob.Status.RUNNING],
            )
            .exists()
        )
        if running:
            return Response(
                {"detail": "A Zendesk import is already running for this team"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        job = ZendeskImportJob.objects.unscoped().create(
            team_id=team_id,
            status=ZendeskImportJob.Status.PENDING,
            job_inputs={
                "subdomain": credentials.subdomain,
                "email_address": credentials.email_address,
                "api_token": credentials.api_token,
            },
        )

        try:
            workflow_id, workflow_run_id = asyncio.run(
                start_zendesk_import_workflow(job_id=str(job.id), team_id=team_id)
            )
            job.workflow_id = workflow_id
            job.workflow_run_id = workflow_run_id
            job.status = ZendeskImportJob.Status.RUNNING
            job.started_at = timezone.now()
            job.save(update_fields=["workflow_id", "workflow_run_id", "status", "started_at", "updated_at"])
        except Exception:
            logger.exception("zendesk_import_workflow_start_failed", job_id=str(job.id), team_id=team_id)
            job.status = ZendeskImportJob.Status.FAILED
            job.latest_error = WORKFLOW_START_FAILED_MESSAGE
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "latest_error", "finished_at", "updated_at"])
            return Response({"detail": WORKFLOW_START_FAILED_MESSAGE}, status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(ZendeskImportJobSerializer(job).data, status=drf_status.HTTP_201_CREATED)

    @extend_schema(
        responses={
            200: ZendeskImportJobSerializer,
            404: ZendeskImportErrorSerializer,
        },
    )
    @action(detail=False, methods=["get"])
    def status(self, request: Request, *args, **kwargs) -> Response:
        job = ZendeskImportJob.objects.unscoped().filter(team_id=self.team_id).order_by("-created_at").first()
        if job is None:
            return Response({"detail": "No Zendesk import job found"}, status=drf_status.HTTP_404_NOT_FOUND)

        return Response(ZendeskImportJobSerializer(job).data)
