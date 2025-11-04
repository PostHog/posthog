import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

from django.db.models import Q, QuerySet
from django.utils.timezone import now

from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import BasePagination, CursorPagination, PageNumberPagination
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.exceptions_capture import capture_exception
from posthog.models import NotificationViewed
from posthog.models.activity_logging.activity_log import ActivityLog, apply_activity_visibility_restrictions
from posthog.models.exported_asset import ExportedAsset
from posthog.tasks import exporter

from .field_discovery import AdvancedActivityLogFieldDiscovery
from .filters import AdvancedActivityLogFilterManager
from .utils import get_activity_log_lookback_restriction


def apply_organization_scoped_filter(
    queryset: QuerySet[ActivityLog], include_org_scoped: bool, team_id: int, organization_id
) -> QuerySet[ActivityLog]:
    """
    Filter activity log queryset by team/org.

    When include_org_scoped is True, includes both:
    - Records with team_id matching the given team
    - Records with team_id=NULL and organization_id matching (org-scoped records)

    When False, only filters by team_id.
    """
    if include_org_scoped:
        return queryset.filter(Q(team_id=team_id) | Q(team_id__isnull=True, organization_id=organization_id))
    else:
        return queryset.filter(team_id=team_id)


class ActivityLogSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer()
    unread = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        exclude = ["team_id"]

    def get_unread(self, obj: ActivityLog) -> bool:
        """is the date of this log item newer than the user's bookmark"""
        if "user" not in self.context:
            return False

        user_bookmark: Optional[NotificationViewed] = NotificationViewed.objects.filter(
            user=self.context["user"]
        ).first()

        if user_bookmark is None:
            return True
        else:
            bookmark_date = user_bookmark.last_viewed_activity_date
            return bookmark_date < obj.created_at.replace(microsecond=obj.created_at.microsecond // 1000 * 1000)


class ActivityLogPagination(BasePagination):
    def __init__(self):
        self.page_number_pagination = PageNumberPagination()
        self.cursor_pagination = CursorPagination()
        self.page_number_pagination.page_size = 100
        self.page_number_pagination.page_size_query_param = "page_size"
        self.page_number_pagination.max_page_size = 1000
        self.cursor_pagination.page_size = 100
        self.cursor_pagination.ordering = "-created_at"

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        if request.query_params.get("page"):
            return self.page_number_pagination.paginate_queryset(queryset, request, view)
        else:
            return self.cursor_pagination.paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        if self.request and self.request.query_params.get("page"):
            return self.page_number_pagination.get_paginated_response(data)
        else:
            return self.cursor_pagination.get_paginated_response(data)


class ActivityLogViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet, mixins.ListModelMixin):
    scope_object = "activity_log"
    queryset = ActivityLog.objects.all()
    serializer_class = ActivityLogSerializer
    pagination_class = ActivityLogPagination
    filter_rewrite_rules = {"project_id": "team_id"}

    def _should_skip_parents_filter(self) -> bool:
        """
        Skip parent filtering when include_organization_scoped=1.
        We'll apply custom org-scoped filtering in safely_get_queryset instead.
        """
        return self.request.query_params.get("include_organization_scoped") == "1"

    def safely_get_queryset(self, queryset) -> QuerySet:
        params = self.request.GET.dict()

        queryset = apply_organization_scoped_filter(
            queryset, params.get("include_organization_scoped") == "1", self.team_id, self.organization.id
        )

        if params.get("user"):
            queryset = queryset.filter(user=params.get("user"))
        if params.get("scope"):
            queryset = queryset.filter(scope=params.get("scope"))
        if params.get("scopes", None):
            scopes = str(params.get("scopes", "")).split(",")
            queryset = queryset.filter(scope__in=scopes)
        if params.get("item_id"):
            queryset = queryset.filter(item_id=params.get("item_id"))

        if params.get("page"):
            queryset = queryset.order_by("-created_at")

        lookback_date = get_activity_log_lookback_restriction(self.organization)
        if lookback_date:
            queryset = queryset.filter(created_at__gte=lookback_date)

        queryset = apply_activity_visibility_restrictions(queryset, self.request.user)

        return queryset


class AdvancedActivityLogFiltersSerializer(serializers.Serializer):
    start_date = serializers.DateTimeField(required=False)
    end_date = serializers.DateTimeField(required=False)
    users = serializers.ListField(child=serializers.UUIDField(), required=False, default=[])
    scopes = serializers.ListField(child=serializers.CharField(), required=False, default=[])
    activities = serializers.ListField(child=serializers.CharField(), required=False, default=[])
    search_text = serializers.CharField(required=False, allow_blank=True)
    detail_filters = serializers.JSONField(required=False, default={})
    hogql_filter = serializers.CharField(required=False, allow_blank=True)
    was_impersonated = serializers.BooleanField(required=False)
    is_system = serializers.BooleanField(required=False)
    item_ids = serializers.ListField(child=serializers.CharField(), required=False, default=[])


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
    queryset = ActivityLog.objects.all()

    def _should_skip_parents_filter(self) -> bool:
        """
        Skip parent filtering when include_organization_scoped=1.
        We'll apply custom org-scoped filtering in safely_get_queryset instead.
        """
        return self.request.query_params.get("include_organization_scoped") == "1"

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

    def safely_get_queryset(self, queryset) -> QuerySet:
        queryset = queryset.select_related("user")

        queryset = apply_organization_scoped_filter(
            queryset,
            self.request.query_params.get("include_organization_scoped") == "1",
            self.team_id,
            self.organization.id,
        )

        # Apply lookback restriction based on feature limits
        lookback_date = get_activity_log_lookback_restriction(self.organization)
        if lookback_date:
            queryset = queryset.filter(created_at__gte=lookback_date)

        return queryset.order_by("-created_at")

    def get_serializer_class(self):
        # This query param is set by the CSV exporter to indicate that the response should be serialized in a flat format
        if self.request.query_params.get("is_csv_export") == "1":
            return ActivityLogFlatExportSerializer

        return super().get_serializer_class()

    def list(self, request, *args, **kwargs):
        filters_serializer = AdvancedActivityLogFiltersSerializer(data=request.query_params)
        filters_serializer.is_valid(raise_exception=True)
        filters = filters_serializer.validated_data

        queryset = self.get_queryset()
        queryset = self.filter_manager.apply_filters(queryset, filters)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["GET"])
    def available_filters(self, request, **kwargs):
        queryset = self.get_queryset()
        available_filters = self.field_discovery.get_available_filters(queryset)
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
