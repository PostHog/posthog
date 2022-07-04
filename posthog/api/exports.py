from typing import Any, Dict

import celery
import structlog
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import mixins, serializers, viewsets
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from posthog.api.documentation import PropertiesSerializer, extend_schema
from posthog.api.routing import StructuredViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.event_usage import report_user_action
from posthog.models import Filter, Insight, Team
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.event.query_event_list import parse_order_by
from posthog.models.exported_asset import ExportedAsset, get_content_response
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.tasks import exporter

logger = structlog.get_logger(__name__)


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
        ]
        read_only_fields = ["id", "created_at", "has_content", "export_context", "filename"]

    def validate(self, attrs):
        if not attrs.get("export_format"):
            raise ValidationError("Must provide export format")

        if attrs.get("export_format", None) != ExportedAsset.ExportFormat.CSV:
            if not attrs.get("dashboard") and not attrs.get("insight"):
                raise ValidationError("Either dashboard or insight is required for an export.")

            if attrs.get("dashboard") and attrs["dashboard"].team.id != self.context["team_id"]:
                raise ValidationError({"dashboard": ["This dashboard does not belong to your team."]})

            if attrs.get("insight") and attrs["insight"].team.id != self.context["team_id"]:
                raise ValidationError({"insight": ["This insight does not belong to your team."]})

        return attrs

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "event",
                OpenApiTypes.STR,
                description="If exporting an event query to CSV. Filter events by event. For example `user sign up` or `$pageview`.",
            ),
            OpenApiParameter(
                "person_id",
                OpenApiTypes.INT,
                description="If exporting an event query to CSV. Filter events by person id.",
            ),
            OpenApiParameter(
                "distinct_id",
                OpenApiTypes.INT,
                description="If exporting an event query to CSV. Filter events by distinct id.",
            ),
            OpenApiParameter(
                "before",
                OpenApiTypes.DATETIME,
                description="If exporting an event query to CSV. Only return events with a timestamp before this time.",
            ),
            OpenApiParameter(
                "after",
                OpenApiTypes.DATETIME,
                description="If exporting an event query to CSV. Only return events with a timestamp after this time.",
            ),
            PropertiesSerializer(required=False),
        ],
    )
    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> ExportedAsset:
        request = self.context["request"]
        validated_data["team_id"] = self.context["team_id"]

        is_csv_export = validated_data.get("export_format") == ExportedAsset.ExportFormat.CSV
        if is_csv_export:
            validated_data["export_context"] = {
                "file_export_type": "list_events",  # hard code to just this one for now
                "filter": Filter(request=request, team=Team.objects.get(pk=validated_data["team_id"])).to_dict(),
                "request_get_query_dict": request.GET.dict(),
                "order_by": parse_order_by(request.GET.get("orderBy")),
                "action_id": request.GET.get("action_id"),
            }
        instance: ExportedAsset = super().create(validated_data)

        task = exporter.export_asset.delay(instance.id)
        try:
            task.get(timeout=10)
            instance.refresh_from_db()
        except celery.exceptions.TimeoutError:
            # If the rendering times out - fine, the frontend will poll instead for the response
            pass
        except NotImplementedError as ex:
            logger.error("exporters.unsupported_export_type", exception=ex)
            raise serializers.ValidationError(
                {"export_format": ["This type of export is not supported for this resource."]}
            )

        report_user_action(
            request.user, "export created", instance.get_analytics_metadata(),
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
                    user=request.user,
                    item_id=insight_id,  # Type: ignore
                    scope="Insight",
                    activity="exported",
                    detail=Detail(
                        name=insight.name if insight.name else insight.derived_name,
                        short_id=insight.short_id,
                        changes=[
                            Change(
                                type="Insight", action="exported", field="export_format", after=instance.export_format
                            )
                        ],
                    ),
                )
            except Insight.DoesNotExist as ex:
                logger.warn("insight_exports.unknown_insight", exception=ex, insight_id=insight_id)
                pass

        return instance


class ExportedAssetViewSet(
    mixins.RetrieveModelMixin, mixins.CreateModelMixin, StructuredViewSetMixin, viewsets.GenericViewSet
):
    queryset = ExportedAsset.objects.order_by("-created_at")
    serializer_class = ExportedAssetSerializer

    authentication_classes = [
        PersonalAPIKeyAuthentication,
        SessionAuthentication,
        BasicAuthentication,
    ]
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    @action(methods=["GET"], detail=True)
    def content(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        instance = self.get_object()
        return get_content_response(instance, request.query_params.get("download") == "true")
