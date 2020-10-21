from typing import Any, Dict, List, Optional

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import ClickhouseEventSerializer, determine_event_conditions
from ee.clickhouse.models.person import get_persons_by_distinct_ids
from ee.clickhouse.models.property import get_property_values_for_key, parse_prop_clauses
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.events import SELECT_EVENT_WITH_ARRAY_PROPS_SQL, SELECT_EVENT_WITH_PROP_SQL, SELECT_ONE_EVENT_SQL
from ee.clickhouse.util import CH_EVENT_ENDPOINT, endpoint_enabled
from posthog.api.event import EventViewSet
from posthog.models import Filter, Person, Team
from posthog.utils import convert_property_value


class ClickhouseEvents(EventViewSet):
    def _get_people(self, query_result: List[Dict], team: Team) -> Dict[str, Any]:
        distinct_ids = [event[5] for event in query_result]
        persons = get_persons_by_distinct_ids(team.pk, distinct_ids)

        distinct_to_person: Dict[str, Person] = {}
        for person in persons:
            for distinct_id in person.distinct_ids:
                distinct_to_person[distinct_id] = person
        return distinct_to_person

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:

        if not endpoint_enabled(CH_EVENT_ENDPOINT, request.user.distinct_id):
            return super().list(request)

        team = request.user.team
        filter = Filter(request=request)
        if request.GET.get("after"):
            filter._date_from = request.GET["after"]
        if request.GET.get("before"):
            filter._date_to = request.GET["before"]
        limit = "LIMIT 101"
        conditions, condition_params = determine_event_conditions(request.GET.dict())
        prop_filters, prop_filter_params = parse_prop_clauses("uuid", filter.properties, team)

        if prop_filters != "":
            query_result = sync_execute(
                SELECT_EVENT_WITH_PROP_SQL.format(conditions=conditions, limit=limit, filters=prop_filters),
                {"team_id": team.pk, **condition_params, **prop_filter_params},
            )
        else:
            query_result = sync_execute(
                SELECT_EVENT_WITH_ARRAY_PROPS_SQL.format(conditions=conditions, limit=limit),
                {"team_id": team.pk, **condition_params},
            )

        result = ClickhouseEventSerializer(
            query_result[0:100], many=True, context={"people": self._get_people(query_result, team),},
        ).data

        if len(query_result) > 100:
            path = request.get_full_path()
            reverse = request.GET.get("orderBy", "-timestamp") != "-timestamp"
            next_url: Optional[str] = request.build_absolute_uri(
                "{}{}{}={}".format(
                    path,
                    "&" if "?" in path else "?",
                    "after" if reverse else "before",
                    query_result[99][3].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                )
            )
        else:
            next_url = None

        return Response({"next": next_url, "results": result})

    def retrieve(self, request: Request, pk: Optional[int] = None, *args: Any, **kwargs: Any) -> Response:

        if not endpoint_enabled(CH_EVENT_ENDPOINT, request.user.distinct_id):
            return super().retrieve(request, pk)

        # TODO: implement getting elements
        team = request.user.team_set.get()
        query_result = sync_execute(SELECT_ONE_EVENT_SQL, {"team_id": team.pk, "event_id": pk},)
        result = ClickhouseEventSerializer(query_result[0], many=False).data

        return Response(result)

    @action(methods=["GET"], detail=False)
    def values(self, request: Request) -> Response:

        if not endpoint_enabled(CH_EVENT_ENDPOINT, request.user.distinct_id):
            return Response(super().get_values(request))

        key = request.GET.get("key")
        team = request.user.team
        result = []
        if key:
            result = get_property_values_for_key(key, team, value=request.GET.get("value"))
        return Response([{"name": convert_property_value(value[0])} for value in result])
