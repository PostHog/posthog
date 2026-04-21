from datetime import timedelta
from typing import Any, Literal

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.timezone import now

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import EventSource, get_event_source, groups
from posthog.models import Insight, Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.exported_asset import ExportedAsset, get_content_response
from posthog.models.organization import Organization
from posthog.security.url_validation import is_url_allowed
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.settings.temporal import TEMPORAL_WORKFLOW_MAX_ATTEMPTS
from posthog.slo.types import SloArea, SloConfig, SloOperation
from posthog.temporal.common.client import async_connect
from posthog.temporal.exports.workflows import ExportAssetWorkflow, ExportAssetWorkflowInputs
from posthog.temporal.session_replay.rasterize_recording.types import RasterizeRecordingInputs

# Full video exports per team per calendar month, tiered by plan.
FULL_VIDEO_EXPORTS_LIMIT_BY_TIER: dict[Literal["free", "paid", "enterprise"], int] = {
    "free": 10,
    "paid": 15,
    "enterprise": 25,
}


def get_full_video_exports_limit_for_organization(organization: Organization | None) -> int:
    """Monthly full video export limit for the organization's plan tier."""
    tier = organization.get_plan_tier() if organization is not None else "free"
    return FULL_VIDEO_EXPORTS_LIMIT_BY_TIER[tier]


logger = structlog.get_logger(__name__)


class ExportedAssetSerializer(serializers.ModelSerializer):
    """Standard ExportedAsset serializer that doesn't return content."""

    has_content = serializers.BooleanField(read_only=True)
    filename = serializers.CharField(read_only=True)

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
        read_only_fields = ["id", "created_at", "has_content", "filename", "expires_after", "exception"]

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

        # Check full video export limit for team (video session recording exports)
        export_format = data.get("export_format")
        export_context = data.get("export_context", {})

        is_full_video_export = export_format in ("video/mp4", "video/webm", "image/gif") and export_context.get(
            "session_recording_id"
        )

        if is_full_video_export:
            # Calculate the start of the current month
            current_time = now()
            start_of_month = current_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            existing_full_video_exports_count = ExportedAsset.objects.filter(
                team_id=self.context["team_id"],
                export_format__in=["video/mp4", "video/webm", "image/gif"],
                export_context__session_recording_id__isnull=False,
                created_at__gte=start_of_month,
            ).count()

            # Plan-tier default with an optional per-team override that acts as a floor.
            # Taking max() preserves the override's original purpose — bumping a team above
            # their tier default — without silently downgrading orgs whose tier default is
            # now higher than a legacy override set during the flat-10 era.
            get_organization = self.context.get("get_organization")
            organization = get_organization() if get_organization is not None else None
            team_limit = get_full_video_exports_limit_for_organization(organization)

            get_team = self.context.get("get_team")
            team = get_team() if get_team is not None else None
            if team is not None and team.extra_settings and "full_video_exports_limit" in team.extra_settings:
                limit_value = team.extra_settings["full_video_exports_limit"]
                try:
                    override_limit = int(limit_value)
                    if override_limit <= 0:
                        raise ValueError("Limit must be positive")
                    team_limit = max(team_limit, override_limit)
                except (ValueError, TypeError):
                    logger.warning(
                        "invalid_full_video_exports_limit",
                        team_id=team.id,
                        limit_value=limit_value,
                        limit_value_type=type(limit_value).__name__,
                    )

            if not self.context["request"].user.is_staff and existing_full_video_exports_count >= team_limit:
                raise ValidationError(
                    {
                        "export_limit_exceeded": [
                            f"Your team has reached the limit of {team_limit} full video exports this month."
                        ]
                    }
                )

        if export_context and export_context.get("heatmap_url"):
            ok, err = is_url_allowed(export_context["heatmap_url"])
            if not ok:
                raise ValidationError({"export_context": [f"heatmap_url not allowed: {err}"]})

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

                logger.info("starting_rasterize_recording_workflow", asset_id=instance.id)

                async def _start():
                    client = await async_connect()
                    await client.execute_workflow(
                        "rasterize-recording",
                        RasterizeRecordingInputs(exported_asset_id=instance.id),
                        id=f"export-video-{instance.id}",
                        task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=int(TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                        execution_timeout=timedelta(hours=1),
                    )

                try:
                    async_to_sync(_start)()
                    logger.info("rasterize_recording_workflow_dispatched", asset_id=instance.id)
                except Exception as e:
                    logger.exception("rasterize_recording_workflow_dispatch_failed", asset_id=instance.id, error=str(e))
                    raise
            else:
                self._start_export_workflow(instance, team, user, force_async=False)
        else:
            self._start_export_workflow(instance, team, user, force_async=True)

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
                # nosemgrep: idor-lookup-without-team (insight_id validated as team-owned in validate())
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

    def _start_export_workflow(
        self, instance: ExportedAsset, team: Team, user: User | None, force_async: bool = False
    ) -> None:
        request = self.context.get("request")
        source = get_event_source(request) if request else EventSource.EXPORT
        distinct_id = str(user.distinct_id) if user else str(team.id)

        workflow_inputs = ExportAssetWorkflowInputs(
            exported_asset_id=instance.id,
            team_id=team.id,
            distinct_id=distinct_id,
            slo=SloConfig(
                operation=SloOperation.EXPORT,
                area=SloArea.ANALYTIC_PLATFORM,
                team_id=team.id,
                resource_id=str(instance.id),
                distinct_id=distinct_id,
                start_properties={
                    "export_format": instance.export_format,
                    "export_type": instance.export_type,
                    "source": source,
                },
                completion_properties={
                    "export_format": instance.export_format,
                    "export_type": instance.export_type,
                    "source": source,
                },
            ),
        )

        async def _run():
            client = await async_connect()
            method = client.start_workflow if force_async else client.execute_workflow
            await method(
                ExportAssetWorkflow.run,
                workflow_inputs,
                id=f"export-asset-{instance.id}",
                task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.TERMINATE_IF_RUNNING,
                execution_timeout=timedelta(minutes=35),
            )

        try:
            async_to_sync(_run)()
        except Exception as e:
            # Swallow workflow failures so the API always returns a 201 with the
            # ExportedAsset record. export_asset_direct populates the exception
            # field before re-raising, so callers (frontend toast, sharing
            # endpoint) can inspect the failure on the asset itself.
            logger.info(
                "export_workflow_failed_gracefully",
                asset_id=instance.id,
                error=str(e),
            )
            return

        logger.info(
            "export_workflow_dispatched" if force_async else "export_workflow_completed",
            asset_id=instance.id,
        )


@extend_schema(tags=["core"])
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
        queryset = queryset.filter(created_by=self.request.user)

        if self.action == "list":
            context_path_filter = self.request.query_params.get("context_path")
            if context_path_filter:
                queryset = queryset.filter(export_context__path__icontains=context_path_filter)

            # Add export format filter
            export_format_filter = self.request.query_params.get("export_format")
            if export_format_filter and export_format_filter in ExportedAsset.get_supported_format_values():
                queryset = queryset.filter(export_format=export_format_filter)

        return queryset

    def safely_get_object(self, queryset):
        instance = get_object_or_404(queryset, pk=self.kwargs["pk"])

        resource = instance.dashboard or instance.insight
        if not resource and instance.export_context:
            session_recording_id = instance.export_context.get("session_recording_id")
            if session_recording_id:
                from posthog.session_recordings.models.session_recording import SessionRecording

                resource = SessionRecording.objects.filter(
                    team_id=instance.team_id, session_id=session_recording_id
                ).first()

        if resource and not self.user_access_control.check_access_level_for_object(resource, required_level="viewer"):
            raise NotFound()

        return instance

    # TODO: This should be removed as it is only used by frontend exporter and can instead use the api/sharing.py endpoint
    @action(methods=["GET"], detail=True, required_scopes=["export:read"])
    def content(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        instance = self.get_object()
        return get_content_response(instance, request.query_params.get("download") == "true")
