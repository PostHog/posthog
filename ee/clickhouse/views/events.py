import json
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.utils.timezone import now
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.event import ClickhouseEventSerializer, determine_event_conditions
from ee.clickhouse.models.person import get_persons_by_distinct_ids
from ee.clickhouse.models.property import get_property_values_for_key, parse_prop_clauses
from ee.clickhouse.queries.clickhouse_session_recording import SessionRecording
from ee.clickhouse.queries.sessions.list import SESSIONS_LIST_DEFAULT_LIMIT, ClickhouseSessionsList
from ee.clickhouse.sql.events import SELECT_EVENT_WITH_ARRAY_PROPS_SQL, SELECT_EVENT_WITH_PROP_SQL, SELECT_ONE_EVENT_SQL
from posthog.api.event import EventViewSet
from posthog.models import Filter, Person, Team
from posthog.models.action import Action
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.utils import convert_property_value, flatten


class ClickhouseEventsViewSet(EventViewSet):
    def _get_people(self, query_result: List[Dict], team: Team) -> Dict[str, Any]:
        distinct_ids = [event[5] for event in query_result]
        persons = get_persons_by_distinct_ids(team.pk, distinct_ids)

        distinct_to_person: Dict[str, Person] = {}
        for person in persons:
            for distinct_id in person.distinct_ids:
                distinct_to_person[distinct_id] = person
        return distinct_to_person

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        team = self.team
        data = {}
        if request.GET.get("after"):
            data.update({"date_from": request.GET["after"]})
        else:
            data.update({"date_from": now() - timedelta(days=1)})
        if request.GET.get("before"):
            data.update({"date_to": request.GET["before"]})
        filter = Filter(data=data, request=request)

        limit = "LIMIT 101"
        conditions, condition_params = determine_event_conditions(request.GET.dict())
        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team.pk)
        if request.GET.get("action_id"):
            action = Action.objects.get(pk=request.GET["action_id"])
            if action.steps.count() == 0:
                return Response({"next": False, "results": []})
            action_query, params = format_action_filter(action)
            prop_filters += " AND {}".format(action_query)
            prop_filter_params = {**prop_filter_params, **params}

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
        query_result = sync_execute(SELECT_ONE_EVENT_SQL, {"team_id": self.team.pk, "event_id": pk},)
        result = ClickhouseEventSerializer(query_result[0], many=False).data

        return Response(result)

    @action(methods=["GET"], detail=False)
    def values(self, request: Request, **kwargs) -> Response:
        key = request.GET.get("key")
        team = self.team
        result = []
        flattened = []
        if key:
            result = get_property_values_for_key(key, team, value=request.GET.get("value"))
            for value in result:
                try:
                    # Try loading as json for dicts or arrays
                    flattened.append(json.loads(value[0]))
                except json.decoder.JSONDecodeError:
                    flattened.append(value[0])
        return Response([{"name": convert_property_value(value)} for value in flatten(flattened)])

    @action(methods=["GET"], detail=False)
    def sessions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        team = self.team
        filter = SessionsFilter(request=request)

        limit = int(request.GET.get("limit", SESSIONS_LIST_DEFAULT_LIMIT))
        offset = int(request.GET.get("offset", 0))

        response = ClickhouseSessionsList().run(team=team, filter=filter, limit=limit + 1, offset=offset)

        if filter.distinct_id:
            try:
                person_ids = get_persons_by_distinct_ids(team.pk, [filter.distinct_id])[0].distinct_ids
                response = [session for i, session in enumerate(response) if response[i]["distinct_id"] in person_ids]
            except IndexError:
                response = []

        if len(response) > limit:
            response.pop()
            return Response({"result": response, "offset": offset + limit})
        else:
            return Response({"result": response,})

    # ******************************************
    # /event/session_recording
    # params:
    # - session_recording_id: (string) id of the session recording
    # ******************************************
    @action(methods=["GET"], detail=False)
    def session_recording(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        session_recording = SessionRecording().run(
            team=self.team, filter=Filter(request=request), session_recording_id=request.GET["session_recording_id"]
        )

        return Response({"result": session_recording})
