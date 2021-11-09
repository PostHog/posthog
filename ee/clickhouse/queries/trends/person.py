from datetime import timedelta
from typing import Dict, Tuple

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from rest_framework.utils.serializer_helpers import ReturnDict

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.person import ClickhousePersonSerializer
from ee.clickhouse.queries.trends.trend_event_query import TrendsEventQuery
from ee.clickhouse.sql.person import GET_PERSONS_FROM_EVENT_QUERY
from posthog.constants import TRENDS_CUMULATIVE, TRENDS_DISPLAY_BY_VALUE
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
        data.update({"date_to": (date_from + relativedelta(weeks=1) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")})
    elif filter.interval == "day":
        data.update({"date_to": date_from})
    elif filter.interval == "hour":
        data.update({"date_to": date_from + timedelta(hours=1)})
    elif filter.interval == "minute":
        data.update({"date_to": date_from + timedelta(minutes=1)})
    return filter.with_data(data)


class TrendsPersonQuery:
    def __init__(self, team: Team, entity: Entity, filter: Filter):
        self.team = team
        self.entity = entity
        self.filter = filter

        if self.filter.display != TRENDS_CUMULATIVE and not self.filter.display in TRENDS_DISPLAY_BY_VALUE:
            self.filter = _handle_date_interval(self.filter)

    def get_query(self) -> Tuple[str, Dict]:
        if self.filter.breakdown_type == "cohort" and self.filter.breakdown_value != "all":
            cohort = Cohort.objects.get(pk=self.filter.breakdown_value, team_id=self.team.pk)
            self.filter = self.filter.with_data(
                {"properties": self.filter.properties + [Property(key="id", value=cohort.pk, type="cohort")]}
            )
        elif (
            self.filter.breakdown_type
            and isinstance(self.filter.breakdown, str)
            and isinstance(self.filter.breakdown_value, str)
        ):
            breakdown_prop = Property(
                key=self.filter.breakdown, value=self.filter.breakdown_value, type=self.filter.breakdown_type
            )
            self.filter = self.filter.with_data({"properties": self.filter.properties + [breakdown_prop]})

        events_query, params = TrendsEventQuery(
            filter=self.filter,
            team_id=self.team.pk,
            entity=self.entity,
            should_join_distinct_ids=True,
            should_join_persons=True,
            extra_fields=["distinct_id", "team_id"],
            extra_person_fields=["created_at", "person_props", "is_identified"],
        ).get_query()

        return (
            GET_PERSONS_FROM_EVENT_QUERY.format(events_query=events_query),
            {**params, "offset": self.filter.offset, "limit": 200},
        )

    def get_people(self) -> ReturnDict:
        query, params = self.get_query()
        people = sync_execute(query, params)

        return ClickhousePersonSerializer(people, many=True).data
