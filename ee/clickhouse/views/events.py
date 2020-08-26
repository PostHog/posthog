from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.client import ch_client
from ee.clickhouse.models.event import determine_event_conditions
from ee.clickhouse.models.property import get_property_values_for_key, parse_filter
from ee.clickhouse.sql.events import SELECT_EVENT_WITH_ARRAY_PROPS_SQL, SELECT_EVENT_WITH_PROP_SQL
from posthog.models.filter import Filter
from posthog.utils import convert_property_value


# reference raw sql for
class ClickhouseEventSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    properties = serializers.SerializerMethodField()
    event = serializers.SerializerMethodField()
    timestamp = serializers.SerializerMethodField()
    person = serializers.SerializerMethodField()
    elements = serializers.SerializerMethodField()

    def get_id(self, event):
        return str(event[0])

    def get_properties(self, event):
        return dict(zip(event[8], event[9]))

    def get_event(self, event):
        return event[1]

    def get_timestamp(self, event):
        return event[3]

    def get_person(self, event):
        return event[5]

    def get_elements(self, event):
        return []


class ClickhouseEvents(viewsets.ViewSet):
    serializer_class = ClickhouseEventSerializer

    def list(self, request):

        team = request.user.team_set.get()
        filter = Filter(request=request)
        limit = "LIMIT 100" if not filter._date_from and not filter._date_to else ""
        conditions, condition_params = determine_event_conditions(request.GET)
        prop_filters, prop_filter_params = parse_filter(filter.properties)

        if prop_filters:
            query_result = ch_client.execute(
                SELECT_EVENT_WITH_PROP_SQL.format(conditions=conditions, limit=limit, filters=prop_filters),
                {"team_id": team.pk, **condition_params, **prop_filter_params},
            )
        else:
            query_result = ch_client.execute(
                SELECT_EVENT_WITH_ARRAY_PROPS_SQL.format(conditions=conditions, limit=limit),
                {"team_id": team.pk, **condition_params},
            )

        result = ClickhouseEventSerializer(query_result, many=True, context={"elements": None, "people": None}).data

        return Response({"next": None, "results": result})

    @action(methods=["GET"], detail=False)
    def values(self, request: Request) -> Response:
        key = request.GET.get("key")
        team = request.user.team_set.get()
        result = []
        if key:
            result = get_property_values_for_key(key, team)
        return Response([{"name": convert_property_value(value[0])} for value in result])

    def retrieve(self, request: Request, pk=None):
        # TODO: implement retrieve event by id
        return Response([])
