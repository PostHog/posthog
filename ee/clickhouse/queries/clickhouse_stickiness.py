from datetime import datetime
from typing import Any, Dict, Tuple

from django.conf import settings
from django.db.models.expressions import F
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.utils.serializer_helpers import ReturnDict
from sentry_sdk.api import capture_exception

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.person import ClickhousePersonSerializer
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import get_trunc_func_ch, parse_timestamps
from ee.clickhouse.sql.person import (
    GET_LATEST_PERSON_DISTINCT_ID_SQL,
    GET_LATEST_PERSON_SQL,
    GET_TEAM_PERSON_DISTINCT_IDS,
    INSERT_COHORT_ALL_PEOPLE_SQL,
    PEOPLE_SQL,
    PERSON_STATIC_COHORT_TABLE,
)
from ee.clickhouse.sql.stickiness.stickiness import STICKINESS_SQL
from ee.clickhouse.sql.stickiness.stickiness_actions import STICKINESS_ACTIONS_SQL
from ee.clickhouse.sql.stickiness.stickiness_people import STICKINESS_PEOPLE_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team
from posthog.queries.stickiness import Stickiness


class ClickhouseStickiness(Stickiness):
    def stickiness(self, entity: Entity, filter: StickinessFilter, team_id: int) -> Dict[str, Any]:

        parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=filter, team_id=team_id)
        prop_filters, prop_filter_params = parse_prop_clauses(
            filter.properties, team_id, filter_test_accounts=filter.filter_test_accounts
        )
        trunc_func = get_trunc_func_ch(filter.interval)

        params: Dict = {"team_id": team_id}
        params = {**params, **prop_filter_params, "num_intervals": filter.total_intervals}
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = entity.get_action()
            action_query, action_params = format_action_filter(action)
            if action_query == "":
                return {}

            params = {**params, **action_params}
            content_sql = STICKINESS_ACTIONS_SQL.format(
                team_id=team_id,
                actions_query=action_query,
                parsed_date_from=parsed_date_from,
                parsed_date_to=parsed_date_to,
                filters=prop_filters,
                trunc_func=trunc_func,
                latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL,
            )
        else:
            content_sql = STICKINESS_SQL.format(
                team_id=team_id,
                event=entity.id,
                parsed_date_from=parsed_date_from,
                parsed_date_to=parsed_date_to,
                filters=prop_filters,
                trunc_func=trunc_func,
                GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
            )

        counts = sync_execute(content_sql, params)
        return self.process_result(counts, filter)

    def _retrieve_people(
        self, target_entity: Entity, filter: StickinessFilter, team: Team, request: Request
    ) -> ReturnDict:
        return retrieve_stickiness_people(target_entity, filter, team)


def _format_entity_filter(entity: Entity) -> Tuple[str, Dict]:
    if entity.type == TREND_FILTER_TYPE_ACTIONS:
        action = entity.get_action()
        action_query, params = format_action_filter(action)
        entity_filter = "AND {}".format(action_query)
    else:
        entity_filter = "AND event = %(event)s"
        params = {"event": entity.id}

    return entity_filter, params


def _process_content_sql(target_entity: Entity, filter: StickinessFilter, team: Team) -> Tuple[str, Dict[str, Any]]:
    parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=filter, team_id=team.pk)
    prop_filters, prop_filter_params = parse_prop_clauses(
        filter.properties, team.pk, filter_test_accounts=filter.filter_test_accounts
    )
    entity_sql, entity_params = _format_entity_filter(entity=target_entity)
    trunc_func = get_trunc_func_ch(filter.interval)

    params: Dict = {
        "team_id": team.pk,
        **prop_filter_params,
        "stickiness_day": filter.selected_interval,
        **entity_params,
        "offset": filter.offset,
    }

    content_sql = STICKINESS_PEOPLE_SQL.format(
        entity_filter=entity_sql,
        parsed_date_from=parsed_date_from,
        parsed_date_to=parsed_date_to,
        filters=prop_filters,
        trunc_func=trunc_func,
        GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
    )
    return content_sql, params


def retrieve_stickiness_people(target_entity: Entity, filter: StickinessFilter, team: Team) -> ReturnDict:

    content_sql, params = _process_content_sql(target_entity, filter, team)

    people = sync_execute(
        PEOPLE_SQL.format(
            content_sql=content_sql,
            query="",
            latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""),
            latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL,
        ),
        params,
    )
    return ClickhousePersonSerializer(people, many=True).data


def insert_stickiness_people_into_cohort(cohort: Cohort, target_entity: Entity, filter: StickinessFilter) -> None:
    content_sql, params = _process_content_sql(target_entity, filter, cohort.team)
    try:
        sync_execute(
            INSERT_COHORT_ALL_PEOPLE_SQL.format(
                content_sql=content_sql,
                query="",
                latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""),
                cohort_table=PERSON_STATIC_COHORT_TABLE,
                latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL,
            ),
            {"cohort_id": cohort.pk, "_timestamp": datetime.now(), **params},
        )
        cohort.is_calculating = False
        cohort.last_calculation = timezone.now()
        cohort.errors_calculating = 0
        cohort.save()
    except Exception as err:
        if settings.DEBUG:
            raise err
        cohort.is_calculating = False
        cohort.errors_calculating = F("errors_calculating") + 1
        cohort.save()
        capture_exception(err)
