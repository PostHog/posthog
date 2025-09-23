import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from django.db.models import Q, QuerySet
from django.utils.timezone import now

from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.activity_log import ActivityLogPagination, ActivityLogSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.exported_asset import ExportedAsset
from posthog.tasks import exporter

from .field_discovery import AdvancedActivityLogFieldDiscovery
from .filters import AdvancedActivityLogFilterManager


class AdvancedActivityLogFiltersSerializer(serializers.Serializer):
    start_date = serializers.DateTimeField(required=False)
    end_date = serializers.DateTimeField(required=False)
    users = serializers.ListField(child=serializers.UUIDField(), required=False, default=[])
    scopes = serializers.ListField(child=serializers.CharField(), required=False, default=[])
    activities = serializers.ListField(child=serializers.CharField(), required=False, default=[])
    search_text = serializers.CharField(required=False, allow_blank=True)
    detail_filters = serializers.JSONField(required=False, default={})
    hogql_filter = serializers.CharField(required=False, allow_blank=True)


class ActivityLogFlatExportSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField()
    project_id = serializers.CharField(source="team_id")
    user_first_name = serializers.CharField(source="user.first_name", default="")
    user_last_name = serializers.CharField(source="user.last_name", default="")
    user_email = serializers.CharField(source="user.email", default="")
    detail = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "organization_id",
            "project_id",
            "user_first_name",
            "user_last_name",
            "user_email",
            "activity",
            "scope",
            "item_id",
            "detail",
            "created_at",
        ]

    def get_detail(self, obj):
        return json.dumps(obj.detail) if obj.detail else ""


class AdvancedActivityLogsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet, mixins.ListModelMixin):
    serializer_class = ActivityLogSerializer
    pagination_class = ActivityLogPagination
    logger = logging.getLogger(__name__)
    filter_rewrite_rules = {"project_id": "team_id"}
    scope_object = "INTERNAL"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._filter_manager = None
        self._field_discovery = None

    @property
    def filter_manager(self) -> AdvancedActivityLogFilterManager:
        if self._filter_manager is None:
            self._filter_manager = AdvancedActivityLogFilterManager()
        return self._filter_manager

    @property
    def field_discovery(self) -> AdvancedActivityLogFieldDiscovery:
        if self._field_discovery is None:
            self._field_discovery = AdvancedActivityLogFieldDiscovery(self.organization.id)
        return self._field_discovery

    def _make_filters_serializable(self, filters_data: dict) -> dict[str, Any]:
        serializable_filters: dict[str, Any] = {}
        for key, value in filters_data.items():
            if isinstance(value, datetime):
                serializable_filters[key] = value.isoformat()
            elif isinstance(value, list):
                serializable_filters[key] = [str(v) if hasattr(v, "hex") else v for v in value]
            else:
                serializable_filters[key] = value
        return serializable_filters

    def _generate_export_filename(self, filters_data: dict, export_format: str) -> str:
        filter_string = json.dumps(filters_data, sort_keys=True)
        filter_hash = hashlib.md5(filter_string.encode()).hexdigest()[:6]

        has_filters = any(filters_data.values())

        current_date = datetime.now().strftime("%Y%m%d")
        filename_base = (
            f"activity_logs_{filter_hash}_{current_date}" if has_filters else f"activity_logs_all_{current_date}"
        )
        return filename_base

    def dangerously_get_queryset(self) -> QuerySet[ActivityLog]:
        include_organization_scoped = self.request.query_params.get("include_organization_scoped")

        base_queryset = ActivityLog.objects.select_related("user")

        if include_organization_scoped == "1":
            # Filter by team_id OR (team_id is null AND organization_id matches)
            base_queryset = base_queryset.filter(
                Q(team_id=self.team_id) | Q(team_id__isnull=True, organization_id=self.organization.id)
            )
        else:
            base_queryset = base_queryset.filter(team_id=self.team_id)

        return base_queryset.order_by("-created_at")

    def get_serializer_class(self):
        # This query param is set by the CSV exporter to indicate that the response should be serialized in a flat format
        if self.request.query_params.get("is_csv_export") == "1":
            return ActivityLogFlatExportSerializer

        return super().get_serializer_class()

    def list(self, request, *args, **kwargs):
        filters_serializer = AdvancedActivityLogFiltersSerializer(data=request.query_params)
        filters_serializer.is_valid(raise_exception=True)
        filters = filters_serializer.validated_data

        queryset = self.filter_manager.apply_filters(self.dangerously_get_queryset(), filters)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["GET"])
    def available_filters(self, request, **kwargs):
        available_filters = self.field_discovery.get_available_filters(self.dangerously_get_queryset())
        return Response(available_filters)

    @action(detail=False, methods=["POST"])
    def export(self, request, **kwargs):
        export_format = request.data.get("format", "csv")

        format_mapping = {
            "csv": ExportedAsset.ExportFormat.CSV,
            "xlsx": ExportedAsset.ExportFormat.XLSX,
        }

        if export_format not in format_mapping:
            return Response({"error": f"Unsupported export format: {export_format}"}, status=400)

        filters_serializer = AdvancedActivityLogFiltersSerializer(data=request.data.get("filters", {}))

        if not filters_serializer.is_valid():
            return Response({"error": "Filters are invalid"}, status=400)

        query_params = {}
        if self.request.query_params.get("include_organization_scoped"):
            query_params["include_organization_scoped"] = "1"

        # Transform body params to query params to include the filters in the export path
        for key, value in filters_serializer.validated_data.items():
            if value:
                if isinstance(value, list):
                    query_params[key] = ",".join(str(v) for v in value)
                elif isinstance(value, dict):
                    query_params[key] = json.dumps(value)
                else:
                    query_params[key] = str(value)

        try:
            serializable_filters = self._make_filters_serializable(filters_serializer.validated_data)
            filename = self._generate_export_filename(serializable_filters, export_format)

            exported_asset = ExportedAsset.objects.create(
                team=self.team,
                export_format=format_mapping[export_format],
                export_context={
                    "path": f"/api/projects/{self.team_id}/advanced_activity_logs/?{urlencode(query_params)}",
                    "method": "GET",
                    "filters": serializable_filters,
                    "filename": filename,
                },
                created_by=request.user,
                expires_after=now() + timedelta(days=7),
            )

            exporter.export_asset.delay(exported_asset.id)

            return Response(
                {
                    "id": exported_asset.id,
                    "export_format": export_format,
                },
                status=202,
            )

        except Exception as e:
            self.logger.exception(f"Failed to create export: {e}")
            capture_exception(e)
            return Response({"error": "Failed to create export"}, status=500)
