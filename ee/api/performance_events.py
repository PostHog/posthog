from typing import Dict, List

import structlog
from rest_framework import request, serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.client import sync_execute
from posthog.performance.sql import PERFORMANCE_EVENT_COLUMNS, _column_names_from_column_definitions
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission

logger = structlog.get_logger(__name__)


class PerformanceEventSerializer(serializers.Serializer):
    # todo, how to make all of these readonly in one go?
    uuid = serializers.UUIDField()
    session_id = serializers.CharField()
    pageview_id = serializers.CharField()
    distinct_id = serializers.CharField()
    time_origin = serializers.DateTimeField()
    entry_type = serializers.CharField()  # LowCardinality(String),
    name = serializers.CharField()
    team_id = serializers.IntegerField()
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
    initiator_type = serializers.CharField()  # LowCardinality(String),
    next_hop_protocol = serializers.CharField()  # LowCardinality(String),
    render_blocking_status = serializers.CharField()  # LowCardinality(String),
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
    navigation_type = serializers.CharField()  # LowCardinality(String),
    unload_event_end = serializers.FloatField()
    unload_event_start = serializers.FloatField()


class PerformanceEvents:
    @classmethod
    def query(cls, session_id: str, pageview_id: str, team_id: int) -> List[Dict]:
        query = """
                select toDateTime64(time_origin + (start_time/1000), 3, 'UTC') as timestamp, * from performance_events
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

        columns = ["timestamp"] + [
            col.strip() for col in _column_names_from_column_definitions(PERFORMANCE_EVENT_COLUMNS).split(", ") if col
        ]
        columnized_results = []
        for result in ch_results:
            columnized_item = {}
            for index, column in enumerate(result):
                if index < len(columns):
                    columnized_item[columns[index]] = column
            columnized_results.append(columnized_item)

        if not columnized_results:
            raise NotFound(detail=f"no results for this session ({session_id}) and pageview ({pageview_id})")

        return columnized_results


class PerformanceEventsViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    serializer_class = PerformanceEventSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    # include_in_docs = True

    def get_queryset(self):
        return None

    def list(self, request: request.Request, *args, **kwargs) -> Response:
        session_id = request.GET.get("session_id")
        pageview_id = request.GET.get("pageview_id")

        if not session_id:
            raise serializers.ValidationError("session_id required")

        results = PerformanceEvents.query(session_id, pageview_id, self.team_id)

        PerformanceEventSerializer(data=results, many=True)

        return Response({"results": results})

    # def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
    #     filters = request.GET.dict()

    #     for key in filters:
    #         if key == "user":
    #             queryset = queryset.filter(created_by=request.user)
    #         elif key == "pinned":
    #             queryset = queryset.filter(pinned=True)
    #         elif key == "static":
    #             queryset = queryset.filter(is_static=True)
    #         elif key == "date_from":
    #             queryset = queryset.filter(last_modified_at__gt=relative_date_parse(request.GET["date_from"]))
    #         elif key == "date_to":
    #             queryset = queryset.filter(last_modified_at__lt=relative_date_parse(request.GET["date_to"]))
    #         elif key == "search":
    #             queryset = queryset.filter(
    #                 Q(name__icontains=request.GET["search"]) | Q(derived_name__icontains=request.GET["search"])
    #             )
    #     return queryset
