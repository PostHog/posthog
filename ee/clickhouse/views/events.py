from typing import Dict

from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from ee.clickhouse.client import ch_client
from ee.clickhouse.models.event import determine_event_conditions
from ee.clickhouse.sql.events import SELECT_EVENT_WITH_ARRAY_PROPS_SQL
from posthog.models.filter import Filter


class ClickhouseEvents(viewsets.ViewSet):
    def list(self, request):
        team = request.user.team_set.get()
        filter = Filter(request=request)
        limit = "LIMIT 100" if not filter._date_from and not filter._date_to else ""
        conditions, condition_params = determine_event_conditions(request.GET)
        query_result = ch_client.execute(
            SELECT_EVENT_WITH_ARRAY_PROPS_SQL.format(conditions=conditions, limit=limit),
            {"team_id": team.pk, **condition_params},
        )
        result = [self._parse_event(res) for res in query_result]
        return Response({"next": None, "results": result})

    def _parse_event(self, result) -> Dict[str, str]:
        return {
            "id": str(result[0]),
            "event": result[1],
            "timestamp": result[3],
            "team_id": result[4],
            "person": result[5],
            "element_hash": result[6],
            "elements": [],
            "properties": dict(zip(result[8], result[9])),
        }

    def retrieve(self, request, pk=None):
        # TODO: implement retrieve event by id
        return Response([])
