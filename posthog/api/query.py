import json
from datetime import datetime, timedelta
from typing import Dict, cast

import posthoganalytics
from dateutil.parser import isoparse
from django.http import HttpResponse, JsonResponse
from django.utils.timezone import now
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from pydantic import BaseModel
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from posthog.api.documentation import extend_schema
from posthog.api.routing import StructuredViewSetMixin
from posthog.cloud_utils import is_cloud
from posthog.hogql.query import execute_hogql_query
from posthog.models import Team, User
from posthog.models.event.events_query import run_events_query
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.time_to_see_data.serializers import SessionEventsQuerySerializer, SessionsQuerySerializer
from posthog.queries.time_to_see_data.sessions import get_session_events, get_sessions
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.schema import EventsQuery, HogQLQuery, RecentPerformancePageViewNode
from posthog.utils import relative_date_parse


def parse_as_date_or(date_string: str | None, default: datetime) -> datetime:
    if not date_string:
        return default

    try:
        timestamp = isoparse(date_string)
    except ValueError:
        timestamp = relative_date_parse(date_string)

    return timestamp or default


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
        return self._process_query(self.team, query_json)

    def post(self, request, *args, **kwargs):
        query_json = request.data
        return self._process_query(self.team, query_json)

    def _process_query(self, team: Team, query_json: Dict) -> JsonResponse:
        try:
            query_kind = query_json.get("kind")
            if query_kind == "EventsQuery":
                events_query = EventsQuery.parse_obj(query_json)
                response = run_events_query(query=events_query, team=team)
                return self._response_to_json_response(response)
            elif query_kind == "HogQLQuery":
                if not self._is_hogql_enabled():
                    return JsonResponse({"error": "HogQL is not enabled for this organization"}, status=400)
                hogql_query = HogQLQuery.parse_obj(query_json)
                response = execute_hogql_query(query=hogql_query.query, team=team)
                return self._response_to_json_response(response)
            elif query_kind == "RecentPerformancePageViewNode":
                try:
                    # noinspection PyUnresolvedReferences
                    from ee.api.performance_events import load_performance_events_recent_pageviews
                except ImportError:
                    return JsonResponse({"error": "Performance events are not enabled for this instance"}, status=400)

                recent_performance_query = RecentPerformancePageViewNode.parse_obj(query_json)
                results = load_performance_events_recent_pageviews(
                    team_id=team.pk,
                    date_from=parse_as_date_or(
                        recent_performance_query.dateRange.date_from, now() - timedelta(hours=1)
                    ),
                    date_to=parse_as_date_or(recent_performance_query.dateRange.date_to, now()),
                )

                return JsonResponse(results, safe=False)  # allow non-dict responses with safe=False
            elif query_kind == "TimeToSeeDataSessionsQuery":
                sessions_query_serializer = SessionsQuerySerializer(data=query_json)
                sessions_query_serializer.is_valid(raise_exception=True)
                return JsonResponse(get_sessions(sessions_query_serializer).data, safe=False)
            elif query_kind == "TimeToSeeDataQuery":
                serializer = SessionEventsQuerySerializer(
                    data={
                        "team_id": team.pk,
                        "session_start": query_json["sessionStart"],
                        "session_end": query_json["sessionEnd"],
                        "session_id": query_json["sessionId"],
                    }
                )
                serializer.is_valid(raise_exception=True)
                return JsonResponse(get_session_events(serializer), safe=False)
            else:
                raise ValidationError("Unsupported query kind: %s" % query_kind)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

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

    def _response_to_json_response(self, response: BaseModel) -> JsonResponse:
        dict = {}
        for key in response.__fields__.keys():
            dict[key] = getattr(response, key)
        return JsonResponse(dict)

    def _is_hogql_enabled(self) -> bool:
        # enabled for all self-hosted
        if not is_cloud():
            return True

        # on PostHog Cloud, use the feature flag
        user: User = cast(User, self.request.user)
        return posthoganalytics.feature_enabled(
            "hogql-queries",
            str(user.distinct_id),
            person_properties={"email": user.email},
            groups={"organization": str(self.organization_id)},
            group_properties={
                "organization": {"id": str(self.organization_id), "created_at": self.organization.created_at}
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
