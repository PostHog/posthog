# NOTE: bad django practice but /ee specifically depends on /posthog so it should be fine
import json
from typing import Any, Dict, Optional

from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.client import ch_client
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.person import ClickhousePersonSerializer
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.clickhouse_stickiness import STICKINESS_ACTIONS_PEOPLE_SQL, STICKINESS_PEOPLE_SQL
from ee.clickhouse.queries.util import parse_timestamps
from posthog.api.action import ActionViewSet
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.team import Team

PERSON_TREND_SQL = """
SELECT DISTINCT distinct_id FROM events WHERE team_id = %(team_id)s AND event = %(event)s {filters} {parsed_date_from} {parsed_date_to}
"""

PERSON_TREND_ACTIONS_SQL = """
SELECT DISTINCT distinct_id FROM events WHERE team_id = %(team_id)s AND id IN ({actions_query}) {filters} {parsed_date_from} {parsed_date_to}
"""

PEOPLE_THROUGH_DISTINCT_SQL = """
SELECT id, created_at, team_id, properties, is_identified, groupArray(distinct_id) FROM person INNER JOIN (
    SELECT DISTINCT person_id, distinct_id FROM person_distinct_id WHERE distinct_id IN ({content_sql})
) as pdi ON person.id = pdi.person_id GROUP BY id, created_at, team_id, properties, is_identified
"""

PEOPLE_SQL = """
SELECT id, created_at, team_id, properties, is_identified, groupArray(distinct_id) FROM person INNER JOIN (
    SELECT DISTINCT person_id, distinct_id FROM person_distinct_id WHERE person_id IN ({content_sql})
) as pdi ON person.id = pdi.person_id GROUP BY id, created_at, team_id, properties, is_identified
"""


class ClickhouseActions(ActionViewSet):
    @action(methods=["GET"], detail=False)
    def people(self, request: Request, *args: Any, **kwargs: Any) -> Response:

        team = request.user.team_set.get()
        filter = Filter(request=request)
        shown_as = request.GET.get("shown_as")
        entity = filter.entities[0]

        current_url = request.get_full_path()
        next_url: Optional[str] = None

        if shown_as is not None and shown_as == "Stickiness":
            stickiness_day = int(request.GET["stickiness_days"])
            serialized_people = self._calculate_stickiness_entity_people(team, entity, filter, stickiness_day)
        else:
            serialized_people = self._calculate_entity_people(team, entity, filter)

        return Response(
            {
                "results": [{"people": serialized_people, "count": len(serialized_people)}],
                "next": next_url,
                "previous": current_url[1:],
            }
        )

    def _calculate_stickiness_entity_people(self, team: Team, entity: Entity, filter: Filter, stickiness_day: int):
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)
        prop_filters, prop_filter_params = parse_prop_clauses("id", filter.properties, team)
        params: Dict = {"team_id": team.pk, **prop_filter_params, "stickiness_day": stickiness_day}

        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            try:
                action = Action.objects.get(pk=entity.id)
                action_query, action_params = format_action_filter(action)
                params = {**params, **action_params}
                content_sql = STICKINESS_ACTIONS_PEOPLE_SQL.format(
                    actions_query=action_query,
                    parsed_date_from=(parsed_date_from or ""),
                    parsed_date_to=(parsed_date_to or ""),
                    filters="{filters}".format(filters=prop_filters) if filter.properties else "",
                )
            except Action.DoesNotExist:
                return []
        else:
            content_sql = STICKINESS_PEOPLE_SQL.format(
                parsed_date_from=(parsed_date_from or ""),
                parsed_date_to=(parsed_date_to or ""),
                filters="{filters}".format(filters=prop_filters) if filter.properties else "",
            )
            params = {**params, "event": entity.id}

        people = ch_client.execute(PEOPLE_SQL.format(content_sql=content_sql), params)
        serialized_people = ClickhousePersonSerializer(people, many=True).data

        return serialized_people

    def _calculate_entity_people(self, team: Team, entity: Entity, filter: Filter):
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)
        prop_filters, prop_filter_params = parse_prop_clauses("id", filter.properties, team)
        params: Dict = {"team_id": team.pk, **prop_filter_params}

        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            try:
                action = Action.objects.get(pk=entity.id)
                action_query, action_params = format_action_filter(action)
                params = {**params, **action_params}
                content_sql = PERSON_TREND_ACTIONS_SQL.format(
                    actions_query=action_query,
                    parsed_date_from=(parsed_date_from or ""),
                    parsed_date_to=(parsed_date_to or ""),
                    filters="{filters}".format(filters=prop_filters) if filter.properties else "",
                )
            except:
                people = []
        else:
            content_sql = PERSON_TREND_SQL.format(
                parsed_date_from=(parsed_date_from or ""),
                parsed_date_to=(parsed_date_to or ""),
                filters="{filters}".format(filters=prop_filters) if filter.properties else "",
            )
            params = {**params, "event": entity.id}
        people = ch_client.execute(PEOPLE_THROUGH_DISTINCT_SQL.format(content_sql=content_sql), params)
        serialized_people = ClickhousePersonSerializer(people, many=True).data

        return serialized_people
