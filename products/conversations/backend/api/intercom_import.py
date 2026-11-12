"""Intercom historical import API for Conversations settings."""

from __future__ import annotations

import asyncio

from django.db import IntegrityError, transaction
from django.utils import timezone

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import (
    serializers,
    status as drf_status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models import User

from products.conversations.backend.models import EmailChannel, EmailChannelKind, IntercomImportJob
from products.conversations.backend.permissions import IsConversationsAdmin
from products.conversations.backend.temporal.intercom_import.client import (
    IntercomCredentials,
    validate_intercom_credentials,
)
from products.conversations.backend.temporal.intercom_import.starter import start_intercom_import_workflow

logger = structlog.get_logger(__name__)

WORKFLOW_START_FAILED_MESSAGE = "Failed to start the import. Please try again or contact support if it persists."
ALREADY_RUNNING_MESSAGE = "An Intercom import is already running for this team"
INTERCOM_IMPORT_FLAG = "product-support-intercom-import"


class IntercomImportStartSerializer(serializers.Serializer):
    region = serializers.ChoiceField(
        choices=IntercomImportJob.Region.choices,
        default=IntercomImportJob.Region.US,
        help_text="Region where the Intercom workspace is hosted: us, eu, or au.",
    )
    access_token = serializers.CharField(
        help_text="Intercom access token with permission to read conversations and contacts.",
        write_only=True,
        max_length=500,
    )
    default_email_channel_id = serializers.UUIDField(
        help_text=(
            "Optional support email channel to attach imported tickets to, so agents can reply by email. "
            "Omit or null to import tickets without an email channel."
        ),
        required=False,
        allow_null=True,
    )


class IntercomImportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Human-readable error message.")


class IntercomImportJobSerializer(serializers.ModelSerializer):
    # The access token lives in the encrypted job_inputs blob and is NEVER serialized; only the
    # region and a has_credentials flag are surfaced.
    region = serializers.SerializerMethodField(help_text="Intercom region used for this import job.")
    has_credentials = serializers.SerializerMethodField(
        help_text="Whether a stored Intercom access token exists for this job (the token is never returned)."
    )

    class Meta:
        model = IntercomImportJob
        fields = [
            "id",
            "status",
            "region",
            "has_credentials",
            "total_conversations",
            "processed_conversations",
            "imported_conversations",
            "skipped_conversations",
            "failed_conversations",
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
            "total_conversations": {"help_text": "Total number of conversations discovered for import."},
            "processed_conversations": {"help_text": "Number of conversations processed so far."},
            "imported_conversations": {"help_text": "Number of conversations imported as tickets."},
            "skipped_conversations": {
                "help_text": "Number of conversations skipped because they were already imported."
            },
            "failed_conversations": {"help_text": "Number of conversations that failed to import."},
            "started_at": {"help_text": "When the import started running."},
            "finished_at": {"help_text": "When the import reached a terminal state."},
            "latest_error": {"help_text": "Generic, user-safe error message when the job failed."},
            "created_at": {"help_text": "When the import job was created."},
            "updated_at": {"help_text": "When the import job was last updated."},
        }

    @extend_schema_field(serializers.ChoiceField(choices=IntercomImportJob.Region.choices, allow_null=True))
    def get_region(self, obj: IntercomImportJob) -> str | None:
        return (obj.job_inputs or {}).get("region")

    def get_has_credentials(self, obj: IntercomImportJob) -> bool:
        return bool((obj.job_inputs or {}).get("access_token"))


class IntercomImportViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    # IsConversationsAdmin checks the routed team's org admin, and the mixin's
    # TeamMemberAccessPermission also requires membership of the routed project.
    scope_object = "INTERNAL"
    serializer_class = IntercomImportJobSerializer
    permission_classes = [IsConversationsAdmin]
    # Class-level attr must be unscoped: the fail-closed manager's .all() reads team context
    # eagerly and there is none at import time. Per-request reads go through the scoped manager.
    queryset = IntercomImportJob.objects.unscoped()

    def safely_get_queryset(self, queryset):
        return IntercomImportJob.objects.all().order_by("-created_at")

    def _flag_enabled(self, request: Request) -> bool:
        # The settings UI is flag-gated per user, so gate the endpoint the same way. A flag-service
        # error counts as disabled.
        user = request.user
        if not isinstance(user, User):
            return False
        try:
            org_id = str(self.team.organization_id)
            return bool(
                posthoganalytics.feature_enabled(
                    INTERCOM_IMPORT_FLAG,
                    str(user.distinct_id),
                    groups={"organization": org_id, "project": str(self.team.id)},
                    group_properties={"organization": {"id": org_id}, "project": {"id": str(self.team.id)}},
                    only_evaluate_locally=False,
                    send_feature_flag_events=False,
                )
            )
        except Exception as e:
            logger.warning("intercom_import_flag_eval_failed", team_id=self.team.id, error=str(e))
            return False

    def _mark_failed_if_pending(self, job: IntercomImportJob) -> None:
        IntercomImportJob.objects.filter(id=job.id, status=IntercomImportJob.Status.PENDING).update(
            status=IntercomImportJob.Status.FAILED,
            latest_error=WORKFLOW_START_FAILED_MESSAGE,
            finished_at=timezone.now(),
            updated_at=timezone.now(),
        )

    @extend_schema(
        request=IntercomImportStartSerializer,
        responses={
            201: IntercomImportJobSerializer,
            400: IntercomImportErrorSerializer,
            403: IntercomImportErrorSerializer,
            500: IntercomImportErrorSerializer,
        },
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        team_id = self.team_id
        if not self._flag_enabled(request):
            return Response({"detail": "Intercom import is not available"}, status=drf_status.HTTP_403_FORBIDDEN)
        if not self.team.conversations_enabled:
            return Response({"detail": "Support is not enabled for this team"}, status=drf_status.HTTP_400_BAD_REQUEST)

        serializer = IntercomImportStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        running = IntercomImportJob.objects.filter(
            status__in=[IntercomImportJob.Status.PENDING, IntercomImportJob.Status.RUNNING],
        ).exists()
        if running:
            return Response({"detail": ALREADY_RUNNING_MESSAGE}, status=drf_status.HTTP_400_BAD_REQUEST)

        default_email_channel_id = data.get("default_email_channel_id")
        if (
            default_email_channel_id is not None
            and not EmailChannel.objects.filter(
                team_id=team_id,
                id=default_email_channel_id,
                kind=EmailChannelKind.SUPPORT,
            ).exists()
        ):
            return Response(
                {"detail": "The selected email channel does not belong to this team"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        credentials = IntercomCredentials(region=data["region"], access_token=data["access_token"])
        if not validate_intercom_credentials(credentials):
            return Response(
                {"detail": "Intercom rejected the access token. Check the token and region."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        # The exists() check above is only a fast path. A partial unique index allows one pending or
        # running job per team, so a concurrent submission that passed the same check fails here.
        try:
            with transaction.atomic():
                job = IntercomImportJob.objects.create(
                    team_id=team_id,
                    status=IntercomImportJob.Status.PENDING,
                    job_inputs={"region": credentials.region, "access_token": credentials.access_token},
                )
        except IntegrityError:
            return Response({"detail": ALREADY_RUNNING_MESSAGE}, status=drf_status.HTTP_400_BAD_REQUEST)

        try:
            workflow_id, workflow_run_id = asyncio.run(
                start_intercom_import_workflow(
                    job_id=str(job.id),
                    team_id=team_id,
                    default_email_channel_id=(
                        str(default_email_channel_id) if default_email_channel_id is not None else None
                    ),
                )
            )
        except Exception:
            logger.exception("intercom_import_workflow_start_failed", job_id=str(job.id), team_id=team_id)
            self._mark_failed_if_pending(job)
            return Response({"detail": WORKFLOW_START_FAILED_MESSAGE}, status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR)

        # The workflow owns status from here: it may already have moved the job on (even to a
        # terminal state for a small workspace), so only advance a job that is still pending.
        now = timezone.now()
        IntercomImportJob.objects.filter(id=job.id).update(
            workflow_id=workflow_id, workflow_run_id=workflow_run_id, updated_at=now
        )
        IntercomImportJob.objects.filter(id=job.id, status=IntercomImportJob.Status.PENDING).update(
            status=IntercomImportJob.Status.RUNNING, started_at=now, updated_at=now
        )
        job.refresh_from_db()

        try:
            report_user_action(
                request.user,
                "support import started",
                {
                    "source": "intercom",
                    "import_job_id": str(job.id),
                    "region": credentials.region,
                    "has_default_email_channel": default_email_channel_id is not None,
                },
                team=self.team,
                request=request,
            )
        except Exception as e:
            capture_exception(e, {"import_job_id": str(job.id)})

        return Response(IntercomImportJobSerializer(job).data, status=drf_status.HTTP_201_CREATED)

    @extend_schema(
        responses={
            200: IntercomImportJobSerializer,
            403: IntercomImportErrorSerializer,
            404: IntercomImportErrorSerializer,
        },
    )
    @action(detail=False, methods=["get"])
    def status(self, request: Request, *args, **kwargs) -> Response:
        if not self._flag_enabled(request):
            return Response({"detail": "Intercom import is not available"}, status=drf_status.HTTP_403_FORBIDDEN)
        job = IntercomImportJob.objects.order_by("-created_at").first()
        if job is None:
            return Response({"detail": "No Intercom import job found"}, status=drf_status.HTTP_404_NOT_FOUND)

        return Response(IntercomImportJobSerializer(job).data)
