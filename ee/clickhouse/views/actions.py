# NOTE: bad django practice but /ee specifically depends on /posthog so it should be fine
import json
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.client import ch_client
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.person import ClickhousePersonSerializer
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.clickhouse_stickiness import STICKINESS_PEOPLE_SQL
from ee.clickhouse.queries.util import parse_timestamps
from posthog.api.action import ActionViewSet
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.team import Team

PERSON_TREND_SQL = """
SELECT DISTINCT distinct_id FROM events WHERE team_id = %(team_id)s {entity_filter} {filters} {parsed_date_from} {parsed_date_to}
"""

PEOPLE_THROUGH_DISTINCT_SQL = """
SELECT id, created_at, team_id, properties, is_identified, groupArray(distinct_id) FROM person INNER JOIN (
    SELECT DISTINCT person_id, distinct_id FROM person_distinct_id WHERE distinct_id IN ({content_sql})
) as pdi ON person.id = pdi.person_id GROUP BY id, created_at, team_id, properties, is_identified
LIMIT 200 OFFSET %(offset)s
"""

PEOPLE_SQL = """
SELECT id, created_at, team_id, properties, is_identified, groupArray(distinct_id) FROM person INNER JOIN (
    SELECT DISTINCT person_id, distinct_id FROM person_distinct_id WHERE person_id IN ({content_sql})
) as pdi ON person.id = pdi.person_id GROUP BY id, created_at, team_id, properties, is_identified
LIMIT 200 OFFSET %(offset)s 
"""


class ClickhouseActions(ActionViewSet):
    @action(methods=["GET"], detail=False)
    def people(self, request: Request, *args: Any, **kwargs: Any) -> Response:

        team = request.user.team_set.get()
        filter = Filter(request=request)
        shown_as = request.GET.get("shown_as")

        if len(filter.entities) >= 1:
            entity = filter.entities[0]
        else:
            entity = Entity({"id": request.GET["entityId"], "type": request.GET["type"]})

        # adhoc date handling. parsed differently with django orm
        if filter.interval == "month":
            filter._date_to = (filter.date_from + timedelta(days=31)).strftime("%Y-%m-%d %H:%M:%S")

        current_url = request.get_full_path()
        next_url: Optional[str] = None

        if shown_as is not None and shown_as == "Stickiness":
            stickiness_day = int(request.GET["stickiness_days"])
            serialized_people = self._calculate_stickiness_entity_people(team, entity, filter, stickiness_day)

        else:
            serialized_people = self._calculate_entity_people(team, entity, filter)

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

        return Response(
            {
                "results": [{"people": serialized_people[0:100], "count": len(serialized_people[0:99])}],
                "next": next_url,
                "previous": current_url[1:],
            }
        )

    def _format_entity_filter(self, entity: Entity) -> Tuple[str, Dict]:
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            try:
                action = Action.objects.get(pk=entity.id)
                action_query, params = format_action_filter(action)
                entity_filter = "AND id IN ({})".format(action_query)

            except Action.DoesNotExist:
                raise ValueError("This action does not exist")
        else:
            entity_filter = "AND event = %(event)s"
            params = {"event": entity.id}

        return entity_filter, params

    def _calculate_stickiness_entity_people(self, team: Team, entity: Entity, filter: Filter, stickiness_day: int):
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)
        prop_filters, prop_filter_params = parse_prop_clauses("id", filter.properties, team)
        entity_sql, entity_params = self._format_entity_filter(entity=entity)

        params: Dict = {
            "team_id": team.pk,
            **prop_filter_params,
            "stickiness_day": stickiness_day,
            **entity_params,
            "offset": filter.offset,
        }

        content_sql = STICKINESS_PEOPLE_SQL.format(
            entity_filter=entity_sql,
            parsed_date_from=(parsed_date_from or ""),
            parsed_date_to=(parsed_date_to or ""),
            filters="{filters}".format(filters=prop_filters) if filter.properties else "",
        )

        people = ch_client.execute(PEOPLE_SQL.format(content_sql=content_sql), params)
        serialized_people = ClickhousePersonSerializer(people, many=True).data

        return serialized_people

    def _calculate_entity_people(self, team: Team, entity: Entity, filter: Filter):
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)
        prop_filters, prop_filter_params = parse_prop_clauses("id", filter.properties, team)
        entity_sql, entity_params = self._format_entity_filter(entity=entity)
        params: Dict = {"team_id": team.pk, **prop_filter_params, **entity_params, "offset": filter.offset}

        content_sql = PERSON_TREND_SQL.format(
            entity_filter=entity_sql,
            parsed_date_from=(parsed_date_from or ""),
            parsed_date_to=(parsed_date_to or ""),
            filters="{filters}".format(filters=prop_filters) if filter.properties else "",
            breakdown_filter="",
        )
        people = ch_client.execute(PEOPLE_THROUGH_DISTINCT_SQL.format(content_sql=content_sql), params)
        serialized_people = ClickhousePersonSerializer(people, many=True).data

        return serialized_people
