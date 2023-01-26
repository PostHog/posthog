import json

from django.http import HttpResponse, JsonResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from posthog.api.documentation import extend_schema
from posthog.api.routing import StructuredViewSetMixin
from posthog.exceptions import RequestParsingError
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
                description="Query node JSON object",
            ),
        ]
    )
    def list(self, request: Request, **kw) -> HttpResponse:
        query_json = self._query_json_from_request(request)
        query_kind = query_json.get("kind")
        if query_kind == "EventsQuery":
            query = EventsQuery.parse_obj(query_json)
            return JsonResponse({"success": "Query is valid!", "query": query.dict()})
        else:
            raise RequestParsingError("Invalid query kind: %s" % query_kind)

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
