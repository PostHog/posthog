import json
from typing import Dict

from django.http import HttpResponse, JsonResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from posthog.api.documentation import extend_schema
from posthog.api.routing import StructuredViewSetMixin
from posthog.models import Team
from posthog.models.event.query_event_list import run_events_query
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.schema import EventsQuery


class QueryViewSet(StructuredViewSetMixin, viewsets.ViewSet):
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]

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
            raise ValidationError("Please provide a query in the request body or as a query parameter.")

        try:

            def parsing_error(ex):
                raise ValidationError(ex)

            query = json.loads(
                query_source, parse_constant=lambda x: parsing_error(f"Unsupported constant found in JSON: {x}")
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as error_main:
            raise ValidationError("Invalid JSON: %s" % (str(error_main)))
        return query


def process_query(team: Team, query_json: Dict) -> Dict:
    query_kind = query_json.get("kind")
    if query_kind == "EventsQuery":
        query = EventsQuery.parse_obj(query_json)
        query_result = run_events_query(
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
        raise ValidationError("Unsupported query kind: %s" % query_kind)
