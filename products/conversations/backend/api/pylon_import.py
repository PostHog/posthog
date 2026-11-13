"""Pylon historical import API for Conversations settings."""

from __future__ import annotations

import asyncio
from datetime import timedelta

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

from products.conversations.backend.models import EmailChannel, EmailChannelKind, PylonImportJob
from products.conversations.backend.permissions import IsConversationsAdmin
from products.conversations.backend.temporal.pylon_import.client import resolve_pylon_credentials
from products.conversations.backend.temporal.pylon_import.starter import (
    pylon_import_workflow_exists,
    start_pylon_import_workflow,
)

logger = structlog.get_logger(__name__)

WORKFLOW_START_FAILED_MESSAGE = "Failed to start the import. Please try again or contact support if it persists."
ALREADY_RUNNING_MESSAGE = "An Pylon import is already running for this team"
PYLON_IMPORT_FLAG = "product-support-pylon-import"
# A started workflow moves its job to running within seconds, so a pending job with no workflow_id
# this old is a candidate orphan; Temporal is still checked before releasing it.
ORPHANED_PENDING_AFTER = timedelta(minutes=10)


class PylonImportStartSerializer(serializers.Serializer):
    api_token = serializers.CharField(
        help_text=(
            "Pylon API token whose role can read issues, messages, and contacts. "
            "The region (US or EU) is detected from the token."
        ),
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


class PylonImportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Human-readable error message.")


class PylonImportJobSerializer(serializers.ModelSerializer):
    # The API token lives in the encrypted job_inputs blob and is NEVER serialized; only the
    # region and a has_credentials flag are surfaced.
    region = serializers.SerializerMethodField(help_text="Pylon region the API token belongs to: us or eu.")
    has_credentials = serializers.SerializerMethodField(
        help_text="Whether a stored Pylon API token exists for this job (the token is never returned)."
    )

    class Meta:
        model = PylonImportJob
        fields = [
            "id",
            "status",
            "region",
            "has_credentials",
            "total_issues",
            "processed_issues",
            "imported_issues",
            "skipped_issues",
            "failed_issues",
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
            "total_issues": {"help_text": "Total number of issues discovered for import."},
            "processed_issues": {"help_text": "Number of issues processed so far."},
            "imported_issues": {"help_text": "Number of issues imported as tickets."},
            "skipped_issues": {"help_text": "Number of issues skipped because they were already imported."},
            "failed_issues": {"help_text": "Number of issues that failed to import."},
            "started_at": {"help_text": "When the import started running."},
            "finished_at": {"help_text": "When the import reached a terminal state."},
            "latest_error": {"help_text": "Generic, user-safe error message when the job failed."},
            "created_at": {"help_text": "When the import job was created."},
            "updated_at": {"help_text": "When the import job was last updated."},
        }

    @extend_schema_field(serializers.ChoiceField(choices=PylonImportJob.Region.choices, allow_null=True))
    def get_region(self, obj: PylonImportJob) -> str | None:
        return (obj.job_inputs or {}).get("region")

    def get_has_credentials(self, obj: PylonImportJob) -> bool:
        return bool((obj.job_inputs or {}).get("api_token"))


class PylonImportViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    # IsConversationsAdmin checks the routed team's org admin, and the mixin's
    # TeamMemberAccessPermission also requires membership of the routed project.
    scope_object = "INTERNAL"
    serializer_class = PylonImportJobSerializer
    permission_classes = [IsConversationsAdmin]
    # Class-level attr must be unscoped: the fail-closed manager's .all() reads team context
    # eagerly and there is none at import time. Per-request reads go through the scoped manager.
    queryset = PylonImportJob.objects.unscoped()

    def safely_get_queryset(self, queryset):
        return PylonImportJob.objects.all().order_by("-created_at")

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
                    PYLON_IMPORT_FLAG,
                    str(user.distinct_id),
                    groups={"organization": org_id, "project": str(self.team.id)},
                    group_properties={"organization": {"id": org_id}, "project": {"id": str(self.team.id)}},
                    only_evaluate_locally=False,
                    send_feature_flag_events=False,
                )
            )
        except Exception as e:
            logger.warning("pylon_import_flag_eval_failed", team_id=self.team.id, error=str(e))
            return False

    def _release_orphaned_reservations(self) -> None:
        now = timezone.now()
        stale = PylonImportJob.objects.filter(
            status=PylonImportJob.Status.PENDING,
            workflow_id__isnull=True,
            created_at__lt=now - ORPHANED_PENDING_AFTER,
        )
        for job in stale:
            # The web process may have died after Temporal accepted the workflow but before saving
            # workflow_id, so ask Temporal before releasing a job a live workflow may still own.
            if asyncio.run(pylon_import_workflow_exists(team_id=job.team_id, job_id=str(job.id))):
                continue
            PylonImportJob.objects.filter(id=job.id, status=PylonImportJob.Status.PENDING).update(
                status=PylonImportJob.Status.FAILED,
                latest_error=WORKFLOW_START_FAILED_MESSAGE,
                finished_at=now,
                updated_at=now,
            )

    def _mark_failed_if_pending(self, job: PylonImportJob) -> None:
        PylonImportJob.objects.filter(id=job.id, status=PylonImportJob.Status.PENDING).update(
            status=PylonImportJob.Status.FAILED,
            latest_error=WORKFLOW_START_FAILED_MESSAGE,
            finished_at=timezone.now(),
            updated_at=timezone.now(),
        )

    @extend_schema(
        request=PylonImportStartSerializer,
        responses={
            201: PylonImportJobSerializer,
            400: PylonImportErrorSerializer,
            403: PylonImportErrorSerializer,
            500: PylonImportErrorSerializer,
        },
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        team_id = self.team_id
        if not self._flag_enabled(request):
            return Response({"detail": "Pylon import is not available"}, status=drf_status.HTTP_403_FORBIDDEN)
        if not self.team.conversations_enabled:
            return Response({"detail": "Support is not enabled for this team"}, status=drf_status.HTTP_400_BAD_REQUEST)

        serializer = PylonImportStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        self._release_orphaned_reservations()
        running = PylonImportJob.objects.filter(
            status__in=[PylonImportJob.Status.PENDING, PylonImportJob.Status.RUNNING],
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

        credentials = resolve_pylon_credentials(data["api_token"])
        if credentials is None:
            return Response(
                {"detail": "Pylon rejected the API token. Check the token and that its role can read issues."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        # The exists() check above is only a fast path. A partial unique index allows one pending or
        # running job per team, so a concurrent submission that passed the same check fails here.
        try:
            with transaction.atomic():
                job = PylonImportJob.objects.create(
                    team_id=team_id,
                    status=PylonImportJob.Status.PENDING,
                    job_inputs={"region": credentials.region, "api_token": credentials.api_token},
                )
        except IntegrityError:
            return Response({"detail": ALREADY_RUNNING_MESSAGE}, status=drf_status.HTTP_400_BAD_REQUEST)

        try:
            workflow_id, workflow_run_id = asyncio.run(
                start_pylon_import_workflow(
                    job_id=str(job.id),
                    team_id=team_id,
                    default_email_channel_id=(
                        str(default_email_channel_id) if default_email_channel_id is not None else None
                    ),
                )
            )
        except Exception:
            logger.exception("pylon_import_workflow_start_failed", job_id=str(job.id), team_id=team_id)
            self._mark_failed_if_pending(job)
            return Response({"detail": WORKFLOW_START_FAILED_MESSAGE}, status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR)

        # The workflow owns status from here: it may already have moved the job on (even to a
        # terminal state for a small workspace), so only advance a job that is still pending.
        now = timezone.now()
        PylonImportJob.objects.filter(id=job.id).update(
            workflow_id=workflow_id, workflow_run_id=workflow_run_id, updated_at=now
        )
        PylonImportJob.objects.filter(id=job.id, status=PylonImportJob.Status.PENDING).update(
            status=PylonImportJob.Status.RUNNING, started_at=now, updated_at=now
        )
        job.refresh_from_db()

        try:
            report_user_action(
                request.user,
                "support import started",
                {
                    "source": "pylon",
                    "import_job_id": str(job.id),
                    "region": credentials.region,
                    "has_default_email_channel": default_email_channel_id is not None,
                },
                team=self.team,
                request=request,
            )
        except Exception as e:
            capture_exception(e, {"import_job_id": str(job.id)})

        return Response(PylonImportJobSerializer(job).data, status=drf_status.HTTP_201_CREATED)

    @extend_schema(
        responses={
            200: PylonImportJobSerializer,
            403: PylonImportErrorSerializer,
            404: PylonImportErrorSerializer,
        },
    )
    @action(detail=False, methods=["get"])
    def status(self, request: Request, *args, **kwargs) -> Response:
        if not self._flag_enabled(request):
            return Response({"detail": "Pylon import is not available"}, status=drf_status.HTTP_403_FORBIDDEN)
        # The settings page disables Start while a job is pending, so release orphans here too.
        self._release_orphaned_reservations()
        job = PylonImportJob.objects.order_by("-created_at").first()
        if job is None:
            return Response({"detail": "No Pylon import job found"}, status=drf_status.HTTP_404_NOT_FOUND)

        return Response(PylonImportJobSerializer(job).data)
