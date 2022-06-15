import json
from datetime import datetime, timedelta
from typing import Any, Dict

import celery
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
from rest_framework import mixins, serializers, viewsets
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from posthog import settings
from posthog.api.dashboard import DashboardSerializer
from posthog.api.insight import InsightSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.event_usage import report_user_action
from posthog.models.exported_asset import ExportedAsset, asset_for_token
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.tasks import exporter
from posthog.utils import render_template

MAX_AGE_CONTENT = 86400  # 1 day


def get_content_response(asset: ExportedAsset, download: bool = False):
    res = HttpResponse(asset.content, content_type=asset.export_format)
    if download:
        res["Content-Disposition"] = f'attachment; filename="{asset.filename}"'

    res["Cache-Control"] = f"max-age={MAX_AGE_CONTENT}"

    return res


class ExportedAssetSerializer(serializers.ModelSerializer):
    """Standard ExportedAsset serializer that doesn't return content."""

    class Meta:
        model = ExportedAsset
        fields = ["id", "dashboard", "insight", "export_format", "created_at", "has_content"]
        read_only_fields = ["id", "created_at", "has_content"]

    def validate(self, attrs):
        if not attrs.get("dashboard") and not attrs.get("insight"):
            raise ValidationError("Either dashboard or insight is required for an export.")

        if attrs.get("dashboard") and attrs["dashboard"].team.id != self.context["team_id"]:
            raise ValidationError({"dashboard": ["This dashboard does not belong to your team."]})

        if attrs.get("insight") and attrs["insight"].team.id != self.context["team_id"]:
            raise ValidationError({"insight": ["This insight does not belong to your team."]})

        return attrs

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> ExportedAsset:
        request = self.context["request"]
        validated_data["team_id"] = self.context["team_id"]

        instance: ExportedAsset = super().create(validated_data)

        task = exporter.export_task.delay(instance.id)
        try:
            task.get(timeout=10)
            instance.refresh_from_db()
        except celery.exceptions.TimeoutError:
            # If the rendering times out - fine, the frontend will poll instead for the response
            pass
        except NotImplementedError as e:
            raise serializers.ValidationError(
                {"export_format": ["This type of export is not supported for this resource."]}
            )

        report_user_action(
            request.user, "export created", instance.get_analytics_metadata(),
        )

        instance.refresh_from_db()

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


class ExportedViewerPageViewSet(mixins.RetrieveModelMixin, StructuredViewSetMixin, viewsets.GenericViewSet):
    queryset = ExportedAsset.objects.none()
    authentication_classes = []  # type: ignore
    permission_classes = []  # type: ignore

    def get_object(self):
        token = self.request.query_params.get("token")
        access_token = self.kwargs.get("access_token")

        asset = None

        if token:
            asset = asset_for_token(token)
        else:
            if settings.DEBUG:
                # NOTE: To aid testing, DEBUG enables loading at any time.
                asset = ExportedAsset.objects.get(access_token=access_token)
            else:
                # Otherwise only assets that haven't been successfully rendered in the last 15 mins are accessible for security's sake
                asset = ExportedAsset.objects.filter(
                    content=None, created_at__gte=datetime.now() - timedelta(minutes=15)
                ).get(access_token=access_token)

        if not asset:
            raise serializers.NotFound()

        return asset

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Any:
        asset = self.get_object()
        context = {"view": self, "request": request}
        export_data = {}

        if request.path.endswith(f".{asset.file_ext}"):
            if not asset.content:
                raise serializers.NotFound()

            return get_content_response(asset, request.query_params.get("download") == "true")

        if asset.dashboard:
            dashboard_data = DashboardSerializer(asset.dashboard, context=context).data
            # We don't want the dashboard to be accidentally loaded via the shared endpoint
            dashboard_data["share_token"] = None
            export_data.update({"dashboard": dashboard_data})

        if asset.insight:
            insight_data = InsightSerializer(asset.insight, many=False, context=context).data
            export_data.update({"insight": insight_data})

        return render_template(
            "exporter.html", request=request, context={"export_data": json.dumps(export_data, cls=DjangoJSONEncoder)},
        )
