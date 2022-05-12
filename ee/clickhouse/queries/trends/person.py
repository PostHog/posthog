from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.trends.trend_event_query import TrendsEventQuery
from ee.clickhouse.sql.person import GET_ACTORS_FROM_EVENT_QUERY
from posthog.constants import NON_TIME_SERIES_DISPLAY_TYPES, TRENDS_CUMULATIVE, PropertyOperatorType
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


class ClickhouseTrendsActors(ActorBaseQuery):
    entity: Entity
    _filter: Filter

    def __init__(self, team: Team, entity: Optional[Entity], filter: Filter, **kwargs):
        if not entity:
            raise ValueError("Entity is required")

        if filter.display != TRENDS_CUMULATIVE and filter.display not in NON_TIME_SERIES_DISPLAY_TYPES:
            filter = _handle_date_interval(filter)

        super().__init__(team, filter, entity, **kwargs)

    @cached_property
    def aggregation_group_type_index(self):
        if self.entity.math == "unique_group":
            return self.entity.math_group_type_index
        return None

    def actor_query(self, limit_actors: Optional[bool] = True) -> Tuple[str, Dict]:
        if self._filter.breakdown_type == "cohort" and self._filter.breakdown_value != "all":
            cohort = Cohort.objects.get(pk=self._filter.breakdown_value, team_id=self._team.pk)
            self._filter = self._filter.with_data(
                {
                    "properties": self._filter.property_groups.combine_properties(
                        PropertyOperatorType.AND, [Property(key="id", value=cohort.pk, type="cohort")]
                    ).to_dict()
                }
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

            self._filter = self._filter.with_data(
                {
                    "properties": self._filter.property_groups.combine_properties(
                        PropertyOperatorType.AND, [breakdown_prop]
                    ).to_dict()
                }
            )

        extra_fields: List[str] = ["distinct_id", "team_id"] if not self.is_aggregating_by_groups else []
        if self._filter.include_recordings:
            extra_fields += ["uuid"]

        events_query, params = TrendsEventQuery(
            filter=self._filter,
            team=self._team,
            entity=self.entity,
            should_join_distinct_ids=not self.is_aggregating_by_groups,
            should_join_persons=not self.is_aggregating_by_groups,
            extra_event_properties=["$window_id", "$session_id"] if self._filter.include_recordings else [],
            extra_fields=extra_fields,
        ).get_query()

        matching_events_select_statement = (
            ", groupUniqArray(10)((timestamp, uuid, $session_id, $window_id)) as matching_events"
            if self._filter.include_recordings
            else ""
        )

        return (
            GET_ACTORS_FROM_EVENT_QUERY.format(
                id_field=self._aggregation_actor_field,
                matching_events_select_statement=matching_events_select_statement,
                events_query=events_query,
                limit="LIMIT %(limit)s" if limit_actors else "",
                offset="OFFSET %(offset)s" if limit_actors else "",
            ),
            {**params, "offset": self._filter.offset, "limit": 200},
        )

    @cached_property
    def _aggregation_actor_field(self) -> str:
        if self.is_aggregating_by_groups:
            group_type_index = self.entity.math_group_type_index
            return f"$group_{group_type_index}"
        else:
            return "person_id"
