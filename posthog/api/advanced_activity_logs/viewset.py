import logging

from django.db.models import Q, QuerySet

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.activity_log import ActivityLogPagination, ActivityLogSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityLog

from .exporters import ExporterFactory
from .field_discovery import AdvancedActivityLogFieldDiscovery
from .filters import AdvancedActivityLogFilterManager
from .serializers import AdvancedActivityLogFiltersSerializer


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

        filters_serializer = AdvancedActivityLogFiltersSerializer(data=request.data.get("filters", {}))
        filters_serializer.is_valid(raise_exception=True)

        queryset = self.filter_manager.apply_filters(self.dangerously_get_queryset(), filters_serializer.validated_data)
        queryset = queryset[:10000]  # Limit export size for starters

        try:
            exporter = ExporterFactory.create_exporter(export_format, queryset)
            return exporter.export()
        except ValueError as e:
            self.logger.exception(f"Invalid export format: {e}")
            capture_exception(e)
            return Response({"error": "Invalid export format"}, status=400)
