from datetime import timedelta
from typing import Dict, Optional, Tuple

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.trends.trend_event_query import TrendsEventQuery
from ee.clickhouse.sql.person import GET_ACTORS_FROM_EVENT_QUERY
from posthog.constants import TRENDS_CUMULATIVE, TRENDS_DISPLAY_BY_VALUE
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.filters.mixins.utils import cached_property
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
    return filter.with_data(data)


class TrendsPersonQuery(ActorBaseQuery):
    entity: Entity
    _filter: Filter

    def __init__(self, team: Team, entity: Optional[Entity], filter: Filter):
        if not entity:
            raise ValueError("Entity is required")

        if filter.display != TRENDS_CUMULATIVE and not filter.display in TRENDS_DISPLAY_BY_VALUE:
            filter = _handle_date_interval(filter)

        super().__init__(team, filter, entity)

    @cached_property
    def is_aggregating_by_groups(self) -> bool:
        return self.entity.math == "unique_group"

    def actor_query(self) -> Tuple[str, Dict]:
        if self._filter.breakdown_type == "cohort" and self._filter.breakdown_value != "all":
            cohort = Cohort.objects.get(pk=self._filter.breakdown_value, team_id=self._team.pk)
            self._filter = self._filter.with_data(
                {"properties": self._filter.properties + [Property(key="id", value=cohort.pk, type="cohort")]}
            )
        elif (
            self._filter.breakdown_type
            and isinstance(self._filter.breakdown, str)
            and isinstance(self._filter.breakdown_value, str)
        ):
            if self._filter.breakdown_type == "group":
                breakdown_prop = Property(
                    key=self._filter.breakdown,
                    value=self._filter.breakdown_value,
                    type=self._filter.breakdown_type,
                    group_type_index=self._filter.breakdown_group_type_index,
                )
            else:
                breakdown_prop = Property(
                    key=self._filter.breakdown, value=self._filter.breakdown_value, type=self._filter.breakdown_type
                )

            self._filter = self._filter.with_data({"properties": self._filter.properties + [breakdown_prop]})

        events_query, params = TrendsEventQuery(
            filter=self._filter,
            team_id=self._team.pk,
            entity=self.entity,
            should_join_distinct_ids=not self.is_aggregating_by_groups,
            should_join_persons=not self.is_aggregating_by_groups,
            extra_fields=[] if self.is_aggregating_by_groups else ["distinct_id", "team_id"],
        ).get_query()

        return (
            GET_ACTORS_FROM_EVENT_QUERY.format(id_field=self._aggregation_actor_field, events_query=events_query),
            {**params, "offset": self._filter.offset, "limit": 200},
        )

    @cached_property
    def _aggregation_actor_field(self) -> str:
        if self.is_aggregating_by_groups:
            group_type_index = self.entity.math_group_type_index
            return f"$group_{group_type_index}"
        else:
            return "person_id"
