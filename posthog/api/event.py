import json
import urllib
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from django.db.models.query import Prefetch
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import mixins, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers
from sentry_sdk import capture_exception

from posthog.api.documentation import PropertiesSerializer, extend_schema
from posthog.api.routing import StructuredViewSetMixin
from posthog.client import query_with_columns, sync_execute
from posthog.models import Element, Filter, Person
from posthog.models.event.events_query import QUERY_DEFAULT_EXPORT_LIMIT, QUERY_DEFAULT_LIMIT, QUERY_MAXIMUM_LIMIT
from posthog.models.event.query_event_list import query_events_list
from posthog.models.event.sql import GET_CUSTOM_EVENTS, SELECT_ONE_EVENT_SQL
from posthog.models.event.util import ClickhouseEventSerializer
from posthog.models.person.util import get_persons_by_distinct_ids
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.property_values import get_property_values_for_key
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.utils import convert_property_value, flatten


class ElementSerializer(serializers.ModelSerializer):
    event = serializers.CharField()

    class Meta:
        model = Element
        fields = [
            "event",
            "text",
            "tag_name",
            "attr_class",
            "href",
            "attr_id",
            "nth_child",
            "nth_of_type",
            "attributes",
            "order",
        ]


class EventViewSet(StructuredViewSetMixin, mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (csvrenderers.PaginatedCSVRenderer,)
    serializer_class = ClickhouseEventSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]

    def _build_next_url(self, request: request.Request, last_event_timestamp: datetime, order_by: List[str]) -> str:
        params = request.GET.dict()
        reverse = "-timestamp" in order_by
        timestamp = last_event_timestamp.astimezone().isoformat()
        if reverse:
            params["before"] = timestamp
        else:
            params["after"] = timestamp
        return request.build_absolute_uri(f"{request.path}?{urllib.parse.urlencode(params)}")

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "event",
                OpenApiTypes.STR,
                description="Filter list by event. For example `user sign up` or `$pageview`.",
            ),
            OpenApiParameter(
                "select",
                OpenApiTypes.STR,
                description="(Experimental) JSON-serialized array of HogQL expressions to return",
                many=True,
            ),
            OpenApiParameter(
                "where",
                OpenApiTypes.STR,
                description="(Experimental) JSON-serialized array of HogQL expressions that must pass",
                many=True,
            ),
            OpenApiParameter("person_id", OpenApiTypes.INT, description="Filter list by person id."),
            OpenApiParameter("distinct_id", OpenApiTypes.INT, description="Filter list by distinct id."),
            OpenApiParameter(
                "before", OpenApiTypes.DATETIME, description="Only return events with a timestamp before this time."
            ),
            OpenApiParameter(
                "after", OpenApiTypes.DATETIME, description="Only return events with a timestamp after this time."
            ),
            OpenApiParameter("limit", OpenApiTypes.INT, description="The maximum number of results to return"),
            PropertiesSerializer(required=False),
        ]
    )
    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        try:
            is_csv_request = self.request.accepted_renderer.format == "csv"

            if self.request.GET.get("limit", None):
                limit = int(self.request.GET.get("limit"))  # type: ignore
            elif is_csv_request:
                limit = QUERY_DEFAULT_EXPORT_LIMIT
            else:
                limit = QUERY_DEFAULT_LIMIT

            limit = min(limit, QUERY_MAXIMUM_LIMIT)

            try:
                offset = int(request.GET["offset"]) if request.GET.get("offset") else 0
            except ValueError:
                offset = 0

            team = self.team
            filter = Filter(request=request, team=self.team)
            order_by: List[str] = (
                list(json.loads(request.GET["orderBy"])) if request.GET.get("orderBy") else ["-timestamp"]
            )

            query_result = query_events_list(
                filter=filter,
                team=team,
                limit=limit,
                offset=offset,
                request_get_query_dict=request.GET.dict(),
                order_by=order_by,
                action_id=request.GET.get("action_id"),
            )

            # Retry the query without the 1 day optimization
            if len(query_result) < limit and not request.GET.get("after"):
                query_result = query_events_list(
                    unbounded_date_from=True,  # only this changed from the query above
                    filter=filter,
                    team=team,
                    limit=limit,
                    offset=offset,
                    request_get_query_dict=request.GET.dict(),
                    order_by=order_by,
                    action_id=request.GET.get("action_id"),
                )

            result = ClickhouseEventSerializer(
                query_result[0:limit], many=True, context={"people": self._get_people(query_result, team)}
            ).data

            next_url: Optional[str] = None
            if not is_csv_request and len(query_result) > limit:
                next_url = self._build_next_url(request, query_result[limit - 1]["timestamp"], order_by)
            return response.Response({"next": next_url, "results": result})

        except Exception as ex:
            capture_exception(ex)
            raise ex

    def _get_people(self, query_result: List[Dict], team: Team) -> Dict[str, Any]:
        distinct_ids = [event["distinct_id"] for event in query_result]
        persons = get_persons_by_distinct_ids(team.pk, distinct_ids)
        persons = persons.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
        distinct_to_person: Dict[str, Person] = {}
        for person in persons:
            for distinct_id in person.distinct_ids:
                distinct_to_person[distinct_id] = person
        return distinct_to_person

    def retrieve(
        self, request: request.Request, pk: Optional[Union[int, str]] = None, *args: Any, **kwargs: Any
    ) -> response.Response:

        if not isinstance(pk, str) or not UUIDT.is_valid_uuid(pk):
            return response.Response(
                {"detail": "Invalid UUID", "code": "invalid", "type": "validation_error"}, status=400
            )
        query_result = query_with_columns(
            SELECT_ONE_EVENT_SQL, {"team_id": self.team.pk, "event_id": pk.replace("-", "")}
        )
        if len(query_result) == 0:
            raise NotFound(detail=f"No events exist for event UUID {pk}")

        query_context = {}
        if request.query_params.get("include_person", False):
            query_context["people"] = self._get_people(query_result, self.team)

        res = ClickhouseEventSerializer(query_result[0], many=False, context=query_context).data
        return response.Response(res)

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        team = self.team

        key = request.GET.get("key")
        event_names = request.GET.getlist("event_name", None)

        flattened = []
        if key == "custom_event":
            events = sync_execute(GET_CUSTOM_EVENTS, {"team_id": team.pk})
            return response.Response([{"name": event[0]} for event in events])
        elif key:
            result = get_property_values_for_key(key, team, event_names, value=request.GET.get("value"))

            for value in result:
                try:
                    # Try loading as json for dicts or arrays
                    flattened.append(json.loads(value[0]))
                except json.decoder.JSONDecodeError:
                    flattened.append(value[0])
        return response.Response([{"name": convert_property_value(value)} for value in flatten(flattened)])


class LegacyEventViewSet(EventViewSet):
    legacy_team_compatibility = True
