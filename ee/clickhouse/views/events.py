from typing import Dict

from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from ee.clickhouse.client import ch_client
from ee.clickhouse.models.event import determine_event_conditions
from ee.clickhouse.sql.events import SELECT_EVENT_WITH_ARRAY_PROPS_SQL
from posthog.models.filter import Filter


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
        query_result = ch_client.execute(
            SELECT_EVENT_WITH_ARRAY_PROPS_SQL.format(conditions=conditions, limit=limit),
            {"team_id": team.pk, **condition_params},
        )

        result = ClickhouseEventSerializer(query_result, many=True).data

        return Response({"next": None, "results": result})

    def retrieve(self, request, pk=None):
        # TODO: implement retrieve event by id
        return Response([])
