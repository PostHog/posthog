# NOTE: bad django practice but /ee specifically depends on /posthog so it should be fine
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.person import ClickhousePersonSerializer
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.person import GET_LATEST_PERSON_SQL, PEOPLE_SQL, PEOPLE_THROUGH_DISTINCT_SQL, PERSON_TREND_SQL
from ee.clickhouse.sql.stickiness.stickiness_people import STICKINESS_PEOPLE_SQL
from posthog.api.action import ActionSerializer, ActionViewSet
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.property import Property
from posthog.models.team import Team


class ClickhouseActionSerializer(ActionSerializer):
    is_calculating = serializers.SerializerMethodField()

    def get_count(self, action: Action) -> Optional[int]:
        if self.context.get("view") and self.context["view"].action != "list":
            query, params = format_action_filter(action)
            if query == "":
                return None
            return sync_execute(
                "SELECT count(1) FROM events WHERE team_id = %(team_id)s AND {}".format(query),
                {"team_id": action.team_id, **params},
            )[0][0]
        return None

    def get_is_calculating(self, action: Action) -> bool:
        return False


class ClickhouseActionsViewSet(ActionViewSet):
    serializer_class = ClickhouseActionSerializer

    # Don't calculate actions in Clickhouse as it's on the fly
    def _calculate_action(self, action: Action) -> None:
        pass

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions_list: List[Dict[Any, Any]] = self.serializer_class(actions, many=True, context={"request": request}).data  # type: ignore
        return Response({"results": actions_list})

    @action(methods=["GET"], detail=False)
    def people(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        team = self.team
        filter = Filter(request=request)
        shown_as = request.GET.get("shown_as")

        if len(filter.entities) >= 1:
            entity = filter.entities[0]
        else:
            entity = Entity({"id": request.GET["entityId"], "type": request.GET["type"]})

        # adhoc date handling. parsed differently with django orm
        date_from = filter.date_from or timezone.now()
        if filter.interval == "month":
            filter._date_to = (date_from + relativedelta(months=1) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        elif filter.interval == "week":
            filter._date_to = date_from + timedelta(weeks=1)
        elif filter.interval == "hour":
            filter._date_to = date_from + timedelta(hours=1)
        elif filter.interval == "minute":
            filter._date_to = date_from + timedelta(minutes=1)

        current_url = request.get_full_path()

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
                entity_filter = "AND {}".format(action_query)

            except Action.DoesNotExist:
                raise ValueError("This action does not exist")
        else:
            entity_filter = "AND event = %(event)s"
            params = {"event": entity.id}

        return entity_filter, params

    def _calculate_stickiness_entity_people(self, team: Team, entity: Entity, filter: Filter, stickiness_day: int):
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)
        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team.pk)
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

        people = sync_execute(
            PEOPLE_SQL.format(
                content_sql=content_sql, query="", latest_person_sql=GET_LATEST_PERSON_SQL.format(query="")
            ),
            params,
        )
        serialized_people = ClickhousePersonSerializer(people, many=True).data

        return serialized_people

    def _calculate_entity_people(self, team: Team, entity: Entity, filter: Filter):
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)
        entity_sql, entity_params = self._format_entity_filter(entity=entity)
        person_filter = ""
        person_filter_params: Dict[str, Any] = {}

        if filter.breakdown_type == "cohort" and filter.breakdown_value != "all":
            cohort = Cohort.objects.get(pk=filter.breakdown_value)
            person_filter, person_filter_params = format_filter_query(cohort)
            person_filter = "AND distinct_id IN ({})".format(person_filter)
        elif (
            filter.breakdown_type == "person"
            and isinstance(filter.breakdown, str)
            and isinstance(filter.breakdown_value, str)
        ):
            person_prop = Property(**{"key": filter.breakdown, "value": filter.breakdown_value, "type": "person"})
            filter.properties.append(person_prop)

        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team.pk)
        params: Dict = {"team_id": team.pk, **prop_filter_params, **entity_params, "offset": filter.offset}

        content_sql = PERSON_TREND_SQL.format(
            entity_filter=entity_sql,
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            filters=prop_filters,
            breakdown_filter="",
            person_filter=person_filter,
        )

        people = sync_execute(
            PEOPLE_THROUGH_DISTINCT_SQL.format(
                content_sql=content_sql, latest_person_sql=GET_LATEST_PERSON_SQL.format(query="")
            ),
            {**params, **person_filter_params},
        )
        serialized_people = ClickhousePersonSerializer(people, many=True).data

        return serialized_people
