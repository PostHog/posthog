import threading
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.http import HttpResponse
from django.utils.timezone import now

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from loginas.utils import is_impersonated_session
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import groups
from posthog.models import Insight, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.exported_asset import ExportedAsset, get_content_response
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.settings.temporal import TEMPORAL_WORKFLOW_MAX_ATTEMPTS
from posthog.tasks import exporter
from posthog.temporal.common.client import async_connect
from posthog.temporal.exports_video.workflow import VideoExportInputs, VideoExportWorkflow

VIDEO_EXPORT_SEMAPHORE = threading.Semaphore(10)  # Allow max 10 concurrent video exports

# Allow max 10 full video exports per team per calendar month
FULL_VIDEO_EXPORTS_LIMIT_PER_TEAM = 10

logger = structlog.get_logger(__name__)

SIX_MONTHS = timedelta(weeks=26)


class ExportedAssetSerializer(serializers.ModelSerializer):
    """Standard ExportedAsset serializer that doesn't return content."""

    class Meta:
        model = ExportedAsset
        fields = [
            "id",
            "dashboard",
            "insight",
            "export_format",
            "created_at",
            "has_content",
            "export_context",
            "filename",
            "expires_after",
            "exception",
        ]
        read_only_fields = ["id", "created_at", "has_content", "filename", "exception"]

    def to_representation(self, instance):
        """Override to show stuck exports as having an exception."""
        data = super().to_representation(instance)

        # Check if this export is stuck (created over HOGQL_INCREASED_MAX_EXECUTION_TIME seconds ago,
        # has no content, and has no recorded exception)
        timeout_threshold = now() - timedelta(seconds=HOGQL_INCREASED_MAX_EXECUTION_TIME + 30)
        if (
            timeout_threshold
            and instance.created_at < timeout_threshold
            and not instance.has_content
            and not instance.exception
        ):
            timeout_message = f"Export failed without throwing an exception. Please try to rerun this export and contact support if it fails to complete multiple times."
            data["exception"] = timeout_message

            distinct_id = (
                self.context["request"].user.distinct_id
                if "request" in self.context and self.context["request"].user
                else str(instance.team.uuid)
            )
            posthoganalytics.capture(
                distinct_id=distinct_id,
                event="export timeout error returned",
                properties={
                    **instance.get_analytics_metadata(),
                    "timeout_message": timeout_message,
                    "stuck_duration_seconds": (now() - instance.created_at).total_seconds(),
                },
                groups=groups(instance.team.organization, instance.team),
            )

        return data

    def validate(self, data: dict) -> dict:
        if not data.get("export_format"):
            raise ValidationError("Must provide export format")

        if not data.get("dashboard") and not data.get("insight") and not data.get("export_context"):
            raise ValidationError("Either dashboard, insight or export_context is required for an export.")

        if data.get("dashboard") and data["dashboard"].team.id != self.context["team_id"]:
            raise ValidationError({"dashboard": ["This dashboard does not belong to your team."]})

        if data.get("insight") and data["insight"].team.id != self.context["team_id"]:
            raise ValidationError({"insight": ["This insight does not belong to your team."]})

        # NEW: Check full video export limit for team (only MP4 exports with "video" mode)
        export_format = data.get("export_format")
        export_context = data.get("export_context", {})
        export_mode = export_context.get("mode")

        if export_format == "video/mp4" and export_mode == "video":
            # Calculate the start of the current month
            current_time = now()
            start_of_month = current_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            existing_full_video_exports_count = ExportedAsset.objects.filter(
                team_id=self.context["team_id"],
                export_format="video/mp4",
                export_context__mode="video",
                created_at__gte=start_of_month,
            ).count()

            if existing_full_video_exports_count >= FULL_VIDEO_EXPORTS_LIMIT_PER_TEAM:
                raise ValidationError(
                    {
                        "export_limit_exceeded": [
                            f"Your team has reached the limit of {FULL_VIDEO_EXPORTS_LIMIT_PER_TEAM} full video exports this month."
                        ]
                    }
                )

        data["expires_after"] = data.get("expires_after", (now() + SIX_MONTHS).date())

        data["team_id"] = self.context["team_id"]
        return data

    def synthetic_create(self, reason: str, *args: Any, **kwargs: Any) -> ExportedAsset:
        # force_async here to avoid blocking patches to the /sharing endpoint
        return self._create_asset(self.validated_data, user=None, reason=reason, force_async=True)

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> ExportedAsset:
        request = self.context["request"]
        return self._create_asset(validated_data, user=request.user, reason=None)

    def _create_asset(
        self,
        validated_data: dict,
        user: User | None,
        reason: str | None,
        force_async: bool = False,
    ) -> ExportedAsset:
        if user is not None:
            validated_data["created_by"] = user

        instance: ExportedAsset = super().create(validated_data)

        if instance.export_format not in ExportedAsset.SUPPORTED_FORMATS:
            raise serializers.ValidationError(
                {"export_format": [f"Export format {instance.export_format} is not supported."]}
            )

        team = instance.team

        posthoganalytics.capture(
            distinct_id=user.distinct_id if user else str(team.uuid),
            event="export requested",
            properties={
                **instance.get_analytics_metadata(),
                "force_async": force_async,
                "reason": reason,
            },
            groups=groups(team.organization, team),
        )

        if not force_async:
            if instance.export_format in ("video/mp4", "video/webm", "image/gif"):
                # recordings-only
                if not (instance.export_context and instance.export_context.get("session_recording_id")):
                    raise serializers.ValidationError(
                        {"export_format": ["Video export supports session recordings only."]}
                    )

                logger.info("starting_video_export_workflow", asset_id=instance.id)

                async def _start():
                    client = await async_connect()
                    await client.execute_workflow(
                        VideoExportWorkflow.run,
                        VideoExportInputs(exported_asset_id=instance.id),
                        id=f"export-video-{instance.id}",
                        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=int(TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    )

                with VIDEO_EXPORT_SEMAPHORE:
                    try:
                        async_to_sync(_start)()
                        logger.info("video_export_workflow_dispatched", asset_id=instance.id)
                    except Exception as e:
                        logger.exception("video_export_workflow_dispatch_failed", asset_id=instance.id, error=str(e))
                        raise
            else:
                exporter.export_asset(instance.id)
        else:
            task = exporter.export_asset.delay(instance.id)
            posthoganalytics.capture(
                distinct_id=user.distinct_id if user else str(team.uuid),
                event="export queued",
                properties={
                    **instance.get_analytics_metadata(),
                    "force_async": force_async,
                    "reason": reason,
                    "task_id": task.id,
                },
                groups=groups(team.organization, team),
            )

        posthoganalytics.capture(
            distinct_id=user.distinct_id if user else str(team.uuid),
            event="export created",
            properties={
                **instance.get_analytics_metadata(),
                "force_async": force_async,
                "reason": reason,
            },
            groups=groups(team.organization, team),
        )

        instance.refresh_from_db()
        insight_id = instance.insight_id
        dashboard_id = instance.dashboard_id
        if insight_id and not dashboard_id:  # we don't log dashboard activity ¯\_(ツ)_/¯
            try:
                insight: Insight = Insight.objects.select_related("team__organization").get(id=insight_id)
                log_activity(
                    organization_id=insight.team.organization.id,
                    team_id=self.context["team_id"],
                    user=user,
                    was_impersonated=is_impersonated_session(self.context["request"])
                    if "request" in self.context
                    else False,
                    item_id=insight_id,  # Type: ignore
                    scope="Insight",
                    activity="exported" if reason is None else f"exported for {reason}",
                    detail=Detail(
                        name=insight.name if insight.name else insight.derived_name,
                        short_id=insight.short_id,
                        changes=[
                            Change(
                                type="Insight",
                                action="exported",
                                field="export_format",
                                after=instance.export_format,
                            )
                        ],
                    ),
                )
            except Insight.DoesNotExist as ex:
                logger.warn(
                    "insight_exports.unknown_insight",
                    exception=ex,
                    insight_id=insight_id,
                )
                pass
        return instance


class ExportedAssetViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "export"
    queryset = ExportedAsset.objects.order_by("-created_at")
    serializer_class = ExportedAssetSerializer

    def safely_get_queryset(self, queryset):
        if self.action == "list":
            queryset = queryset.filter(created_by=self.request.user)

            context_path_filter = self.request.query_params.get("context_path")
            if context_path_filter:
                queryset = queryset.filter(export_context__path__icontains=context_path_filter)

            # Add export format filter
            export_format_filter = self.request.query_params.get("export_format")
            if export_format_filter and export_format_filter in ExportedAsset.get_supported_format_values():
                queryset = queryset.filter(export_format=export_format_filter)

        return queryset

    # TODO: This should be removed as it is only used by frontend exporter and can instead use the api/sharing.py endpoint
    @action(methods=["GET"], detail=True, required_scopes=["export:read"])
    def content(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        instance = self.get_object()
        return get_content_response(instance, request.query_params.get("download") == "true")
