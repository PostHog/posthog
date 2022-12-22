from typing import Dict, List, Optional

from rest_framework import request, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.models.performance.sql import PERFORMANCE_EVENT_COLUMNS, _column_names_from_column_definitions
from posthog.permissions import (
    PremiumFeaturePermission,
    ProjectMembershipNecessaryPermissions,
    TeamMemberAccessPermission,
)


class PerformanceEventSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    session_id = serializers.CharField()
    pageview_id = serializers.CharField()
    distinct_id = serializers.CharField()
    timestamp = serializers.DateTimeField()
    time_origin = serializers.DateTimeField()
    entry_type = serializers.CharField()
    name = serializers.CharField()
    current_url = serializers.CharField()
    start_time = serializers.FloatField()
    duration = serializers.FloatField()
    redirect_start = serializers.FloatField()
    redirect_end = serializers.FloatField()
    worker_start = serializers.FloatField()
    fetch_start = serializers.FloatField()
    domain_lookup_start = serializers.FloatField()
    domain_lookup_end = serializers.FloatField()
    connect_start = serializers.FloatField()
    secure_connection_start = serializers.FloatField()
    connect_end = serializers.FloatField()
    request_start = serializers.FloatField()
    response_start = serializers.FloatField()
    response_end = serializers.FloatField()
    decoded_body_size = serializers.IntegerField()
    encoded_body_size = serializers.IntegerField()
    initiator_type = serializers.CharField()
    next_hop_protocol = serializers.CharField()
    render_blocking_status = serializers.CharField()
    response_status = serializers.IntegerField()
    transfer_size = serializers.IntegerField()
    largest_contentful_paint_element = serializers.CharField()
    largest_contentful_paint_render_time = serializers.FloatField()
    largest_contentful_paint_load_time = serializers.FloatField()
    largest_contentful_paint_size = serializers.FloatField()
    largest_contentful_paint_id = serializers.CharField()
    largest_contentful_paint_url = serializers.CharField()
    dom_complete = serializers.FloatField()
    dom_content_loaded_event = serializers.FloatField()
    dom_interactive = serializers.FloatField()
    load_event_end = serializers.FloatField()
    load_event_start = serializers.FloatField()
    redirect_count = serializers.IntegerField()
    navigation_type = serializers.CharField()
    unload_event_end = serializers.FloatField()
    unload_event_start = serializers.FloatField()


class PerformanceEvents:
    @classmethod
    def query(cls, team_id: int, session_id: str, pageview_id: Optional[str] = None) -> List[Dict]:
        query = """
                select * from performance_events
                prewhere team_id = %(team_id)s
                and session_id = %(session_id)s
                order by timestamp
                """

        if pageview_id:
            query += " and pageview_id = %(pageview_id)s"
        ch_results = sync_execute(
            query,
            {"team_id": team_id, "session_id": session_id, "pageview_id": pageview_id},
        )

        columns = [
            col.strip() for col in _column_names_from_column_definitions(PERFORMANCE_EVENT_COLUMNS).split(", ") if col
        ]
        columnized_results = []
        for result in ch_results:
            columnized_item = {}
            for index, column in enumerate(result):
                if index < len(columns):
                    columnized_item[columns[index]] = column
            columnized_results.append(columnized_item)

        return columnized_results


class PerformanceEventsViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    serializer_class = PerformanceEventSerializer
    permission_classes = [
        IsAuthenticated,
        PremiumFeaturePermission,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]
    premium_feature = AvailableFeature.RECORDINGS_PERFORMANCE

    def get_queryset(self):
        return None

    def list(self, request: request.Request, *args, **kwargs) -> Response:
        session_id = request.GET.get("session_id")
        pageview_id = request.GET.get("pageview_id")

        if not session_id:
            raise serializers.ValidationError("session_id required")

        results = PerformanceEvents.query(
            self.team_id,
            session_id,
            pageview_id,
        )

        serializer = PerformanceEventSerializer(data=results, many=True)
        serializer.is_valid(raise_exception=False)

        return Response({"results": serializer.data})
