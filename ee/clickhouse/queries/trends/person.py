from datetime import timedelta
from typing import Any, Dict, List, Tuple

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


class TrendsPersonQuery:
    def __init__(self, team: Team, entity: Entity, filter: Filter):
        self.team = team
        self.entity = entity
        self.filter = filter

        if self.filter.display != TRENDS_CUMULATIVE:
            self.filter = _handle_date_interval(self.filter)

    def get_events_query(self) -> Tuple[str, Dict]:
        "Returns query + params for getting relevant distinct_ids/person_ids for this filter"

        parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=self.filter, team_id=self.team.pk)
        entity_sql, entity_params = format_entity_filter(entity=self.entity)
        person_filter = ""
        person_filter_params: Dict[str, Any] = {}

        if self.filter.breakdown_type == "cohort" and self.filter.breakdown_value != "all":
            cohort = Cohort.objects.get(pk=self.filter.breakdown_value)
            person_filter, person_filter_params = format_filter_query(cohort)
            person_filter = "AND distinct_id IN ({})".format(person_filter)
        elif (
            self.filter.breakdown_type
            and isinstance(self.filter.breakdown, str)
            and isinstance(self.filter.breakdown_value, str)
        ):
            breakdown_prop = Property(
                key=self.filter.breakdown, value=self.filter.breakdown_value, type=self.filter.breakdown_type
            )
            self.filter.properties.append(breakdown_prop)

        prop_filters, prop_filter_params = parse_prop_clauses(
            self.filter.properties, self.team.pk, filter_test_accounts=self.filter.filter_test_accounts
        )
        params: Dict = {
            "team_id": self.team.pk,
            **prop_filter_params,
            **entity_params,
            **person_filter_params,
            "offset": self.filter.offset,
        }

        if self.entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
            active_user_params = get_active_user_params(self.filter, self.entity, self.team.pk)
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
        return content_sql, params

    def get_people(self) -> List[Dict]:
        content_sql, params = self.get_query()

        people = sync_execute(
            (PEOPLE_SQL if self.entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE] else PEOPLE_THROUGH_DISTINCT_SQL).format(
                content_sql=content_sql,
                latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""),
                GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
            ),
            params,
        )
        serialized_people = ClickhousePersonSerializer(people, many=True).data

        return serialized_people
