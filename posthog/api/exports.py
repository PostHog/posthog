from datetime import timedelta
from typing import Any, Dict

import celery
import requests.exceptions
import structlog
from django.http import HttpResponse
from django.utils.timezone import now
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.api.routing import StructuredViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import Insight, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.exported_asset import ExportedAsset, get_content_response
from posthog.tasks import exporter
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
        ]
        read_only_fields = ["id", "created_at", "has_content", "filename"]

    def validate(self, data: Dict) -> Dict:
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
        return self._create_asset(self.validated_data, user=None, asset_generation_timeout=0.01, reason=reason)

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> ExportedAsset:
        request = self.context["request"]
        return self._create_asset(validated_data, user=request.user, asset_generation_timeout=10, reason=None)

    def _create_asset(
        self,
        validated_data: Dict,
        user: User | None,
        asset_generation_timeout: float,
        reason: str | None,
    ) -> ExportedAsset:
        if user is not None:
            validated_data["created_by"] = user

        instance: ExportedAsset = super().create(validated_data)
        self.generate_export_sync(instance, timeout=asset_generation_timeout)

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

    @staticmethod
    def generate_export_sync(instance: ExportedAsset, timeout: float = 10) -> None:
        task = exporter.export_asset.delay(instance.id)
        try:
            task.get(timeout=timeout)
            instance.refresh_from_db()
        except celery.exceptions.TimeoutError:
            # If the rendering times out - fine, the frontend will poll instead for the response
            pass
        except requests.exceptions.MissingSchema:
            # regression test see https://github.com/PostHog/posthog/issues/11204
            pass
        except NotImplementedError as ex:
            logger.error("exporters.unsupported_export_type", exception=ex, exc_info=True)
            raise serializers.ValidationError(
                {"export_format": ["This type of export is not supported for this resource."]}
            )


class ExportedAssetViewSet(
    StructuredViewSetMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ExportedAsset.objects.order_by("-created_at")
    serializer_class = ExportedAssetSerializer

    # TODO: This should be removed as it is only used by frontend exporter and can instead use the api/sharing.py endpoint
    @action(methods=["GET"], detail=True)
    def content(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        instance = self.get_object()
        return get_content_response(instance, request.query_params.get("download") == "true")
