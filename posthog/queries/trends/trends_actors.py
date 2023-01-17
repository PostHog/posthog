import datetime
import json
from typing import Any, Dict, List, Optional, Tuple, cast

from posthog.constants import PropertyOperatorType
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.person.sql import GET_ACTORS_FROM_EVENT_QUERY
from posthog.models.property import Property
from posthog.models.team import Team
from posthog.queries.actor_base_query import ActorBaseQuery
from posthog.queries.trends.trends_event_query import TrendsEventQuery
from posthog.queries.trends.util import (
    PROPERTY_MATH_FUNCTIONS,
    is_series_group_based,
    offset_time_series_date_by_interval,
    process_math,
)


class TrendsActors(ActorBaseQuery):
    ACTOR_VALUES_INCLUDED = True
    QUERY_TYPE = "trends_actors"

    entity: Entity
    _filter: Filter

    def __init__(self, team: Team, entity: Optional[Entity], filter: Filter, hogql_values: Dict, **kwargs):
        if not entity:
            raise ValueError("Entity is required")
        if filter._date_from is not None and filter._date_to is not None and filter._date_from == filter._date_to:
            # Before 2023, actors modal URLs for non-cumulative time-series insight data points had `date_to`
            # (`filter._date_to`) equal to `date_from` (`filter._date_from`). To obtain the actual `date_to`,
            # we always had to calculate it here by adding a `filter.interval` unit to `date_from`.
            # This was annoying and only made it harder to reason about the API, so it's no longer how actors modal
            # URLs behave. Now we only do this handling at this level for backwards compatibility (cached results)
            # via the `date_from == date_to` check - all new requests have a "fully qualified" date range.
            filter = filter.with_data(
                {
                    "date_to": offset_time_series_date_by_interval(
                        cast(datetime.datetime, filter.date_from), filter=filter, team=team
                    )
                }
            )
        super().__init__(team, filter, hogql_values, entity, **kwargs)

    @cached_property
    def aggregation_group_type_index(self):
        if is_series_group_based(self.entity):
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
            if self._filter.using_histogram:
                lower_bound, upper_bound = json.loads(self._filter.breakdown_value)
                breakdown_props = [
                    Property(
                        key=self._filter.breakdown,
                        value=lower_bound,
                        operator="gte",
                        type=self._filter.breakdown_type,
                        group_type_index=self._filter.breakdown_group_type_index
                        if self._filter.breakdown_type == "group"
                        else None,
                    ),
                    Property(
                        key=self._filter.breakdown,
                        value=upper_bound,
                        operator="lt",
                        type=self._filter.breakdown_type,
                        group_type_index=self._filter.breakdown_group_type_index
                        if self._filter.breakdown_type == "group"
                        else None,
                    ),
                ]
            else:
                breakdown_props = [
                    Property(
                        key=self._filter.breakdown,
                        value=self._filter.breakdown_value,
                        type=self._filter.breakdown_type,
                        group_type_index=self._filter.breakdown_group_type_index
                        if self._filter.breakdown_type == "group"
                        else None,
                    )
                ]

            self._filter = self._filter.with_data(
                {
                    "properties": self._filter.property_groups.combine_properties(
                        PropertyOperatorType.AND, breakdown_props
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
            should_join_distinct_ids=not self.is_aggregating_by_groups
            and not self._team.person_on_events_querying_enabled,
            extra_event_properties=["$window_id", "$session_id"] if self._filter.include_recordings else [],
            extra_fields=extra_fields,
            using_person_on_events=self._team.person_on_events_querying_enabled,
        ).get_query()

        matching_events_select_statement = (
            ", groupUniqArray(100)((timestamp, uuid, $session_id, $window_id)) as matching_events"
            if self._filter.include_recordings
            else ""
        )

        actor_value_expression, actor_value_params = self._aggregation_actor_value_expression_with_params

        return (
            GET_ACTORS_FROM_EVENT_QUERY.format(
                id_field=self._aggregation_actor_field,
                actor_value_expression=actor_value_expression,
                matching_events_select_statement=matching_events_select_statement,
                events_query=events_query,
                limit="LIMIT %(limit)s" if limit_actors else "",
                offset="OFFSET %(offset)s" if limit_actors else "",
            ),
            {**params, **actor_value_params, "offset": self._filter.offset, "limit": self._filter.limit or 100},
        )

    @cached_property
    def _aggregation_actor_field(self) -> str:
        if self.is_aggregating_by_groups:
            group_type_index = self.entity.math_group_type_index
            return f"$group_{group_type_index}"
        else:
            return "person_id"

    @cached_property
    def _aggregation_actor_value_expression_with_params(self) -> Tuple[str, Dict[str, Any]]:
        if self.entity.math in PROPERTY_MATH_FUNCTIONS:
            math_aggregate_operation, _, math_params = process_math(self.entity, self._team, event_table_alias="e")
            return math_aggregate_operation, math_params
        return "count()", {}
