from datetime import timedelta
from typing import Any, Dict

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_entity_filter
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.person import ClickhousePersonSerializer
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.trends.util import get_active_user_params
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.person import (
    GET_LATEST_PERSON_SQL,
    GET_TEAM_PERSON_DISTINCT_IDS,
    PEOPLE_SQL,
    PEOPLE_THROUGH_DISTINCT_SQL,
    PERSON_TREND_SQL,
)
from ee.clickhouse.sql.trends.volume import PERSONS_ACTIVE_USER_SQL
from posthog.constants import MONTHLY_ACTIVE, TRENDS_CUMULATIVE, WEEKLY_ACTIVE
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.property import Property
from posthog.models.team import Team


def calculate_entity_people(team: Team, entity: Entity, filter: Filter):
    content_sql, params = get_person_query(team, entity, filter)

    people = sync_execute(
        (PEOPLE_SQL if entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE] else PEOPLE_THROUGH_DISTINCT_SQL).format(
            content_sql=content_sql,
            latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""),
            GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
        ),
        params,
    )
    serialized_people = ClickhousePersonSerializer(people, many=True).data

    return serialized_people


def _handle_date_interval(filter: Filter) -> Filter:
    # adhoc date handling. parsed differently with django orm
    date_from = filter.date_from or timezone.now()
    data: Dict = {}
    if filter.interval == "month":
        data.update(
            {"date_to": (date_from + relativedelta(months=1) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")}
        )
    elif filter.interval == "week":
        data.update({"date_to": (date_from + relativedelta(weeks=1)).strftime("%Y-%m-%d %H:%M:%S")})
    elif filter.interval == "day":
        data.update({"date_to": (date_from)})
    elif filter.interval == "hour":
        data.update({"date_to": date_from + timedelta(hours=1)})
    elif filter.interval == "minute":
        data.update({"date_to": date_from + timedelta(minutes=1)})
    return Filter(data={**filter._data, **data})


def get_person_query(team: Team, entity: Entity, filter: Filter):

    if filter.display != TRENDS_CUMULATIVE:
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
        breakdown_prop = Property(key=filter.breakdown, value=filter.breakdown_value, type=filter.breakdown_type)
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
