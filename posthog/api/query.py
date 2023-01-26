import json
from typing import Dict

from django.http import HttpResponse, JsonResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from posthog.api.documentation import extend_schema
from posthog.api.routing import StructuredViewSetMixin
from posthog.exceptions import RequestParsingError
from posthog.models import Team
from posthog.models.event.query_event_list import query_events_list_v2
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.rate_limit import PassThroughClickHouseBurstRateThrottle, PassThroughClickHouseSustainedRateThrottle
from posthog.schema import EventsQuery


class QueryViewSet(StructuredViewSetMixin, viewsets.ViewSet):
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    throttle_classes = [PassThroughClickHouseBurstRateThrottle, PassThroughClickHouseSustainedRateThrottle]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "query",
                OpenApiTypes.STR,
                description="Query node JSON string",
            ),
        ]
    )
    def list(self, request: Request, **kw) -> HttpResponse:
        query_json = self._query_json_from_request(request)
        query_result = process_query(self.team, query_json)
        return JsonResponse(query_result)

    def post(self, request, *args, **kwargs):
        query_json = request.data
        query_result = process_query(self.team, query_json)
        return JsonResponse(query_result)

    def _query_json_from_request(self, request):
        if request.method == "POST":
            if request.content_type in ["", "text/plain", "application/json"]:
                query_source = request.body
            else:
                query_source = request.POST.get("query")
        else:
            query_source = request.GET.get("query")

        if query_source is None:
            raise RequestParsingError("Please provide a query in the request body or as a query parameter.")

        try:
            # parse_constant gets called in case of NaN, Infinity etc
            # default behaviour is to put those into the DB directly
            # but we just want it to return None
            query = json.loads(query_source, parse_constant=lambda x: None)
        except (json.JSONDecodeError, UnicodeDecodeError) as error_main:
            raise RequestParsingError("Invalid JSON: %s" % (str(error_main)))
        return query


def process_query(team: Team, query_json: Dict) -> Dict:
    query_kind = query_json.get("kind")
    if query_kind == "EventsQuery":
        query = EventsQuery.parse_obj(query_json)
        query_result = query_events_list_v2(
            team=team,
            query=query,
        )
        # :KLUDGE: Calling `query_result.dict()` without the following deconstruction fails with a cryptic error
        return {
            "columns": query_result.columns,
            "types": query_result.types,
            "results": query_result.results,
            "hasMore": query_result.hasMore,
        }
    else:
        raise RequestParsingError("Unsupported query kind: %s" % query_kind)
