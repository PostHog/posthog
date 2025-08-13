from datetime import timedelta
from typing import Any

import posthoganalytics
import structlog
from django.http import HttpResponse
from django.utils.timezone import now
from rest_framework import mixins, serializers, viewsets
from posthog.api.utils import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import Insight, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.exported_asset import ExportedAsset, get_content_response
from posthog.tasks import exporter
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from loginas.utils import is_impersonated_session

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

        blocking_exports = posthoganalytics.feature_enabled(
            "blocking-exports",
            str(team.uuid),
            groups={
                "organization": str(team.organization_id),
                "project": str(team.id),
            },
            group_properties={
                "organization": {
                    "id": str(team.organization_id),
                },
                "project": {
                    "id": str(team.id),
                },
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
        if blocking_exports and not force_async:
            exporter.export_asset(instance.id)
        else:
            exporter.export_asset.delay(instance.id)

        if user is not None:
            report_user_action(user, "export created", instance.get_analytics_metadata())

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
            return queryset.filter(created_by=self.request.user)
        return queryset

    # TODO: This should be removed as it is only used by frontend exporter and can instead use the api/sharing.py endpoint
    @action(methods=["GET"], detail=True, required_scopes=["export:read"])
    def content(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        instance = self.get_object()
        return get_content_response(instance, request.query_params.get("download") == "true")
