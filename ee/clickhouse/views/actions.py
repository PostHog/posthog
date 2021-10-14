# NOTE: bad django practice but /ee specifically depends on /posthog so it should be fine
from datetime import datetime
from typing import Any, Dict, List, Optional

from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_csv import renderers as csvrenderers

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.queries.trends.person import TrendsPersonQuery
from ee.clickhouse.sql.person import INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID, PERSON_STATIC_COHORT_TABLE
from posthog.api.action import ActionSerializer, ActionViewSet
from posthog.api.utils import get_target_entity
from posthog.models.action import Action
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters import Filter


class ClickhouseActionSerializer(ActionSerializer):
    is_calculating = serializers.SerializerMethodField()

    def get_is_calculating(self, action: Action) -> bool:
        return False


class ClickhouseActionsViewSet(ActionViewSet):
    serializer_class = ClickhouseActionSerializer

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions_list: List[Dict[Any, Any]] = self.serializer_class(actions, many=True, context={"request": request}).data  # type: ignore
        return Response({"results": actions_list})

    @action(methods=["GET"], detail=False)
    def people(self, request: Request, *args: Any, **kwargs: Any) -> Response:  # type: ignore
        team = self.team
        filter = Filter(request=request, team=self.team)
        entity = get_target_entity(request)

        current_url = request.get_full_path()
        serialized_people = TrendsPersonQuery(team, entity, filter).get_people()

        current_url = request.get_full_path()
        next_url: Optional[str] = request.get_full_path()
        offset = filter.offset
        if len(serialized_people) > 100 and next_url:
            if "offset" in next_url:
                next_url = next_url[1:]
                next_url = next_url.replace("offset=" + str(offset), "offset=" + str(offset + 100))
            else:
                next_url = request.build_absolute_uri(
                    "{}{}offset={}".format(next_url, "&" if "?" in next_url else "?", offset + 100)
                )
        else:
            next_url = None

        if request.accepted_renderer.format == "csv":
            csvrenderers.CSVRenderer.header = ["Distinct ID", "Internal ID", "Email", "Name", "Properties"]
            content = [
                {
                    "Name": person.get("properties", {}).get("name"),
                    "Distinct ID": person.get("distinct_ids", [""])[0],
                    "Internal ID": person.get("id"),
                    "Email": person.get("properties", {}).get("email"),
                    "Properties": person.get("properties", {}),
                }
                for person in serialized_people
            ]
            return Response(content)

        return Response(
            {
                "results": [{"people": serialized_people[0:100], "count": len(serialized_people[0:100])}],
                "next": next_url,
                "previous": current_url[1:],
            }
        )

    @action(methods=["GET"], detail=True)
    def count(self, request: Request, **kwargs) -> Response:  # type: ignore
        action = self.get_object()
        query, params = format_action_filter(action)
        if query == "":
            return Response({"count": 0})

        results = sync_execute(
            "SELECT count(1) FROM events WHERE team_id = %(team_id)s AND {}".format(query),
            {"team_id": action.team_id, **params},
        )
        return Response({"count": results[0][0]})


def insert_entity_people_into_cohort(cohort: Cohort, entity: Entity, filter: Filter):
    query, params = TrendsPersonQuery(cohort.team, entity, filter).get_query()
    sync_execute(
        INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID.format(cohort_table=PERSON_STATIC_COHORT_TABLE, query=query),
        {"cohort_id": cohort.pk, "_timestamp": datetime.now(), **params},
    )


class LegacyClickhouseActionsViewSet(ClickhouseActionsViewSet):
    legacy_team_compatibility = True
