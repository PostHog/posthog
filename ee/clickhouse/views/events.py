import json

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.element import get_elements_by_elements_hash
from ee.clickhouse.models.event import ClickhouseEventSerializer, determine_event_conditions
from ee.clickhouse.models.property import get_property_values_for_key, parse_filter
from ee.clickhouse.sql.events import SELECT_EVENT_WITH_ARRAY_PROPS_SQL, SELECT_EVENT_WITH_PROP_SQL, SELECT_ONE_EVENT_SQL
from ee.clickhouse.util import CH_EVENT_ENDPOINT, endpoint_enabled
from posthog.api.event import EventViewSet
from posthog.models.filter import Filter
from posthog.utils import convert_property_value


class ClickhouseEvents(viewsets.ViewSet):
    serializer_class = ClickhouseEventSerializer

    def list(self, request):

        if not endpoint_enabled(CH_EVENT_ENDPOINT, request.user.distinct_id):
            return EventViewSet().list(request)

        team = request.user.team_set.get()
        filter = Filter(request=request)
        limit = "LIMIT 100" if not filter._date_from and not filter._date_to else ""
        conditions, condition_params = determine_event_conditions(request.GET)
        prop_filters, prop_filter_params = parse_filter(filter.properties)

        if prop_filters:
            query_result = sync_execute(
                SELECT_EVENT_WITH_PROP_SQL.format(conditions=conditions, limit=limit, filters=prop_filters),
                {"team_id": team.pk, **condition_params, **prop_filter_params},
            )
        else:
            query_result = sync_execute(
                SELECT_EVENT_WITH_ARRAY_PROPS_SQL.format(conditions=conditions, limit=limit),
                {"team_id": team.pk, **condition_params},
            )

        result = ClickhouseEventSerializer(query_result, many=True, context={"elements": None, "people": None}).data

        return Response({"next": None, "results": result})

    def retrieve(self, request, pk=None):

        if not endpoint_enabled(CH_EVENT_ENDPOINT, request.user.distinct_id):
            return EventViewSet().retrieve(request, pk)

        # TODO: implement getting elements
        team = request.user.team_set.get()
        query_result = sync_execute(SELECT_ONE_EVENT_SQL, {"team_id": team.pk, "event_id": pk},)
        result = ClickhouseEventSerializer(query_result[0], many=False).data

        if result["elements_hash"]:
            result["elements"] = get_elements_by_elements_hash(result["elements_hash"], team.pk)

        return Response(result)

    @action(methods=["GET"], detail=False)
    def values(self, request: Request) -> Response:

        if not endpoint_enabled(CH_EVENT_ENDPOINT, request.user.distinct_id):
            return Response(EventViewSet().get_values(request))

        key = request.GET.get("key")
        team = request.user.team
        result = []
        if key:
            result = get_property_values_for_key(key, team)
        return Response([{"name": json.loads(convert_property_value(value[0]))} for value in result])
