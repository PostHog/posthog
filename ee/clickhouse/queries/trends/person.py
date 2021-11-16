from datetime import timedelta
from typing import Dict, Tuple

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from rest_framework.utils.serializer_helpers import ReturnDict

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.group import ClickhouseGroupSerializer
from ee.clickhouse.models.person import ClickhousePersonSerializer
from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.trends.trend_event_query import TrendsEventQuery
from ee.clickhouse.sql.person import GET_ACTORS_FROM_EVENT_QUERY
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


class TrendsPersonQuery(ActorBaseQuery):
    def __init__(self, team: Team, entity: Entity, filter: Filter):
        new_filter = filter

        if filter.display != TRENDS_CUMULATIVE and not filter.display in TRENDS_DISPLAY_BY_VALUE:
            new_filter = _handle_date_interval(filter)

        super().__init__(team, new_filter, entity)

    def people_query(self) -> Tuple[str, Dict]:
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
            if self.filter.breakdown_type == "group":
                breakdown_prop = Property(
                    key=self.filter.breakdown,
                    value=self.filter.breakdown_value,
                    type=self.filter.breakdown_type,
                    group_type_index=self.filter.breakdown_group_type_index,
                )
            else:
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

        select_fields = {
            "created_at": f"any(created_at)",
            "properties": f"any(person_props)",
            "is_identified": f"any(is_identified)",
            "distinct_ids": f"arrayReduce('groupUniqArray', groupArray(distinct_id))",
        }

        formatted_select_fields = self._format_select_fields(fields=select_fields)

        return (
            GET_ACTORS_FROM_EVENT_QUERY.format(
                id_field="person_id", select_fields=formatted_select_fields, events_query=events_query
            ),
            {**params, "offset": self.filter.offset, "limit": 200},
        )

    def groups_query(self) -> Tuple[str, Dict]:
        group_type_index = self.entity.math_group_type_index
        events_query, params = TrendsEventQuery(
            filter=self.filter,
            team_id=self.team.pk,
            entity=self.entity,
            should_join_distinct_ids=False,
            should_join_persons=False,
            extra_group_fields={group_type_index: ["created_at", "group_properties"]},
        ).get_query()

        select_fields = {
            "created_at": f"any(group_created_at_{group_type_index})",
            "properties": f"any(group_properties_{group_type_index})",
        }

        formatted_select_fields = self._format_select_fields(fields=select_fields)

        return (
            GET_ACTORS_FROM_EVENT_QUERY.format(
                id_field=f"$group_{group_type_index}",
                select_fields=formatted_select_fields,
                events_query=events_query,
                group_type_index=self.entity.math_group_type_index,
            ),
            {**params, "offset": self.filter.offset, "limit": 200},
        )

    def _format_select_fields(self, fields: Dict[str, str]) -> str:
        return " ".join(f", {selector} AS {column_name}" for column_name, selector in fields.items())
