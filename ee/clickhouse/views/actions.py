# NOTE: bad django practice but /ee specifically depends on /posthog so it should be fine
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_csv import renderers as csvrenderers
from sentry_sdk.api import capture_exception

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter, format_entity_filter
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.person import ClickhousePersonSerializer
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.trends.util import get_active_user_params
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.person import (
    GET_LATEST_PERSON_DISTINCT_ID_SQL,
    GET_LATEST_PERSON_SQL,
    GET_TEAM_PERSON_DISTINCT_IDS,
    INSERT_COHORT_ALL_PEOPLE_THROUGH_DISTINCT_SQL,
    PEOPLE_SQL,
    PEOPLE_THROUGH_DISTINCT_SQL,
    PERSON_STATIC_COHORT_TABLE,
    PERSON_TREND_SQL,
)
from ee.clickhouse.sql.trends.volume import PERSONS_ACTIVE_USER_SQL
from posthog.api.action import ActionSerializer, ActionViewSet
from posthog.api.utils import get_target_entity
from posthog.constants import MONTHLY_ACTIVE, WEEKLY_ACTIVE
from posthog.models.action import Action
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.property import Property
from posthog.models.team import Team


class ClickhouseActionSerializer(ActionSerializer):
    is_calculating = serializers.SerializerMethodField()

    def get_is_calculating(self, action: Action) -> bool:
        return False

    def _calculate_action(self, action: Action) -> None:
        # Don't calculate actions in Clickhouse as it's on the fly
        pass


class ClickhouseActionsViewSet(ActionViewSet):
    serializer_class = ClickhouseActionSerializer

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions_list: List[Dict[Any, Any]] = self.serializer_class(actions, many=True, context={"request": request}).data  # type: ignore
        return Response({"results": actions_list})

    @action(methods=["GET"], detail=False)
    def people(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        team = self.team
        filter = Filter(request=request)
        entity = get_target_entity(request)

        current_url = request.get_full_path()
        serialized_people = calculate_entity_people(team, entity, filter)

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
                "results": [{"people": serialized_people[0:100], "count": len(serialized_people[0:99])}],
                "next": next_url,
                "previous": current_url[1:],
            }
        )

    @action(methods=["GET"], detail=True)
    def count(self, request: Request, **kwargs) -> Response:
        action = self.get_object()
        query, params = format_action_filter(action)
        if query == "":
            return Response({"count": 0})

        results = sync_execute(
            "SELECT count(1) FROM events WHERE team_id = %(team_id)s AND {}".format(query),
            {"team_id": action.team_id, **params},
        )
        return Response({"count": results[0][0]})


def _handle_date_interval(filter: Filter) -> Filter:
    # adhoc date handling. parsed differently with django orm
    date_from = filter.date_from or timezone.now()
    data = {}
    if filter.interval == "month":
        data.update(
            {"date_to": (date_from + relativedelta(months=1) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")}
        )
    elif filter.interval == "week":
        data.update({"date_to": (date_from + relativedelta(weeks=1)).strftime("%Y-%m-%d %H:%M:%S")})
    elif filter.interval == "hour":
        data.update({"date_to": date_from + timedelta(hours=1)})
    elif filter.interval == "minute":
        data.update({"date_to": date_from + timedelta(minutes=1)})
    return Filter(data={**filter._data, **data})


def _process_content_sql(team: Team, entity: Entity, filter: Filter):

    filter = _handle_date_interval(filter)

    parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=filter, team_id=team.pk)
    entity_sql, entity_params = format_entity_filter(entity=entity)
    person_filter = ""
    person_filter_params: Dict[str, Any] = {}

    if filter.breakdown_type == "cohort" and filter.breakdown_value != "all":
        cohort = Cohort.objects.get(pk=filter.breakdown_value)
        person_filter, person_filter_params = format_filter_query(cohort)
        person_filter = "AND distinct_id IN ({})".format(person_filter)
    elif filter.breakdown_type and isinstance(filter.breakdown, str) and isinstance(filter.breakdown_value, str):
        breakdown_prop = Property(
            **{"key": filter.breakdown, "value": filter.breakdown_value, "type": filter.breakdown_type}
        )
        filter.properties.append(breakdown_prop)

    prop_filters, prop_filter_params = parse_prop_clauses(
        filter.properties, team.pk, filter_test_accounts=filter.filter_test_accounts
    )
    params: Dict = {"team_id": team.pk, **prop_filter_params, **entity_params, "offset": filter.offset}

    if entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
        active_user_params = get_active_user_params(filter, entity, team.pk)
        content_sql = PERSONS_ACTIVE_USER_SQL.format(
            entity_query=f"AND {entity_sql}",
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            filters=prop_filters,
            breakdown_filter="",
            person_filter=person_filter,
            GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
            **active_user_params,
        )
    else:
        content_sql = PERSON_TREND_SQL.format(
            entity_filter=f"AND {entity_sql}",
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            filters=prop_filters,
            breakdown_filter="",
            person_filter=person_filter,
        )
    return content_sql, {**params, **person_filter_params}


def calculate_entity_people(team: Team, entity: Entity, filter: Filter):
    content_sql, params = _process_content_sql(team, entity, filter)

    people = sync_execute(
        (PEOPLE_SQL if entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE] else PEOPLE_THROUGH_DISTINCT_SQL).format(
            content_sql=content_sql,
            latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""),
            latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL,
        ),
        params,
    )
    serialized_people = ClickhousePersonSerializer(people, many=True).data

    return serialized_people


def insert_entity_people_into_cohort(cohort: Cohort, entity: Entity, filter: Filter):
    content_sql, params = _process_content_sql(cohort.team, entity, filter)
    sync_execute(
        INSERT_COHORT_ALL_PEOPLE_THROUGH_DISTINCT_SQL.format(
            cohort_table=PERSON_STATIC_COHORT_TABLE,
            content_sql=content_sql,
            latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""),
            latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL,
        ),
        {"cohort_id": cohort.pk, "_timestamp": datetime.now(), **params},
    )


class LegacyClickhouseActionsViewSet(ClickhouseActionsViewSet):
    legacy_team_compatibility = True
