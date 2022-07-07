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
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers
from sentry_sdk import capture_exception

from posthog.api.documentation import PropertiesSerializer, extend_schema
from posthog.api.routing import StructuredViewSetMixin
from posthog.client import query_with_columns, sync_execute
from posthog.models import Element, Filter, Person
from posthog.models.event.query_event_list import parse_order_by, query_events_list
from posthog.models.event.sql import GET_CUSTOM_EVENTS, SELECT_ONE_EVENT_SQL
from posthog.models.event.util import ClickhouseEventSerializer
from posthog.models.person.util import get_persons_by_distinct_ids
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.property_values import get_property_values_for_key
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
    pagination_class = LimitOffsetPagination
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    # Return at most this number of events in CSV export
    CSV_EXPORT_DEFAULT_LIMIT = 3_500
    CSV_EXPORT_MAXIMUM_LIMIT = 100_000

    def _build_next_url(self, request: request.Request, last_event_timestamp: datetime) -> str:
        params = request.GET.dict()
        reverse = "-timestamp" in parse_order_by(request.GET.get("orderBy"))
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
            OpenApiParameter("person_id", OpenApiTypes.INT, description="Filter list by person id."),
            OpenApiParameter("distinct_id", OpenApiTypes.INT, description="Filter list by distinct id."),
            OpenApiParameter(
                "before", OpenApiTypes.DATETIME, description="Only return events with a timestamp before this time."
            ),
            OpenApiParameter(
                "after", OpenApiTypes.DATETIME, description="Only return events with a timestamp after this time."
            ),
            PropertiesSerializer(required=False),
        ],
    )
    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        try:
            is_csv_request = self.request.accepted_renderer.format == "csv"

            if self.request.GET.get("limit", None):
                limit = int(self.request.GET.get("limit"))  # type: ignore
            elif is_csv_request:
                limit = self.CSV_EXPORT_DEFAULT_LIMIT
            else:
                limit = 100

            if is_csv_request:
                limit = min(limit, self.CSV_EXPORT_MAXIMUM_LIMIT)

            team = self.team
            filter = Filter(request=request, team=self.team)

            query_result = query_events_list(
                filter=filter,
                team=team,
                limit=limit,
                request_get_query_dict=request.GET.dict(),
                order_by=parse_order_by(request.GET.get("orderBy")),
                action_id=request.GET.get("action_id"),
            )

            # Retry the query without the 1 day optimization
            if len(query_result) < limit and not request.GET.get("after"):
                query_result = query_events_list(
                    filter=filter,
                    team=team,
                    long_date_from=True,
                    limit=limit,
                    request_get_query_dict=request.GET.dict(),
                    order_by=parse_order_by(request.GET.get("orderBy")),
                    action_id=request.GET.get("action_id"),
                )

            result = ClickhouseEventSerializer(
                query_result[0:limit], many=True, context={"people": self._get_people(query_result, team),},
            ).data

            next_url: Optional[str] = None
            if not is_csv_request and len(query_result) > limit:
                next_url = self._build_next_url(request, query_result[limit - 1]["timestamp"])

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
                {"detail": "Invalid UUID", "code": "invalid", "type": "validation_error",}, status=400
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
        key = request.GET.get("key")
        team = self.team
        flattened = []
        if key == "custom_event":
            events = sync_execute(GET_CUSTOM_EVENTS, {"team_id": team.pk})
            return response.Response([{"name": event[0]} for event in events])
        elif key:
            result = get_property_values_for_key(key, team, value=request.GET.get("value"))
            for value in result:
                try:
                    # Try loading as json for dicts or arrays
                    flattened.append(json.loads(value[0]))
                except json.decoder.JSONDecodeError:
                    flattened.append(value[0])
        return response.Response([{"name": convert_property_value(value)} for value in flatten(flattened)])


class LegacyEventViewSet(EventViewSet):
    legacy_team_compatibility = True
