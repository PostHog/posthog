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

from products.conversations.backend.models import EmailChannel, ZendeskImportJob
from products.conversations.backend.permissions import IsConversationsAdmin
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
    default_email_channel_id = serializers.UUIDField(
        help_text=(
            "Optional fallback email channel for tickets whose original Zendesk recipient doesn't "
            "match a configured support address (or isn't an email). Omit or null to leave those "
            "tickets without an email channel."
        ),
        required=False,
        allow_null=True,
    )


class ZendeskImportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Human-readable error message.")


class ZendeskImportJobSerializer(serializers.ModelSerializer):
    # Surface only the account-level subdomain so the settings form can show which Zendesk account
    # was last used. The agent email and API token live in the same encrypted blob but are NEVER
    # serialized: the email is a personal login that must not leak to other admins. `has_credentials`
    # lets the UI show "configured" without disclosing the operator's identity.
    subdomain = serializers.SerializerMethodField(help_text="Zendesk subdomain used for this import job.")
    has_credentials = serializers.SerializerMethodField(
        help_text="Whether stored Zendesk credentials exist for this job (the token/email are never returned)."
    )

    class Meta:
        model = ZendeskImportJob
        fields = [
            "id",
            "status",
            "subdomain",
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

    def get_subdomain(self, obj: ZendeskImportJob) -> str | None:
        return (obj.job_inputs or {}).get("subdomain")

    def get_has_credentials(self, obj: ZendeskImportJob) -> bool:
        return bool((obj.job_inputs or {}).get("api_token"))


class ZendeskImportViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    # Settings-only, admin-gated, session-auth endpoint — not exposed as a public API scope.
    # IsConversationsAdmin gates on the *routed* team's org admin; the mixin's
    # TeamMemberAccessPermission additionally enforces membership of the routed project,
    # so an org admin can't import into a project they can't access.
    scope_object = "INTERNAL"
    serializer_class = ZendeskImportJobSerializer
    permission_classes = [IsConversationsAdmin]
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

        default_email_channel_id = data.get("default_email_channel_id")
        if (
            default_email_channel_id is not None
            and not EmailChannel.objects.filter(team_id=team_id, id=default_email_channel_id).exists()
        ):
            return Response(
                {"detail": "The selected default email channel does not belong to this team"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

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
                start_zendesk_import_workflow(
                    job_id=str(job.id),
                    team_id=team_id,
                    default_email_channel_id=(
                        str(default_email_channel_id) if default_email_channel_id is not None else None
                    ),
                )
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
