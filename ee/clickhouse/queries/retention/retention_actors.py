import dataclasses
from typing import Dict, List, Optional, Tuple

from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.retention.clickhouse_retention import (
    BreakdownValues,
    build_returning_event_query,
    build_target_event_query,
)
from ee.clickhouse.sql.retention.retention import RETENTION_BREAKDOWN_ACTOR_SQL
from posthog.client import substitute_params, sync_execute
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.team import Team


@dataclasses.dataclass
class AppearanceRow:
    """
    Container for the rows of the "Appearance count" query.
    """

    actor_id: str
    appearance_count: int
    # This is actually the number of days from first event to the current event.
    appearances: List[float]


class ClickhouseRetentionActors(ActorBaseQuery):
    _filter: RetentionFilter

    def __init__(self, team: Team, filter: RetentionFilter):
        super().__init__(team, filter)

    @cached_property
    def aggregation_group_type_index(self):
        return self._filter.aggregation_group_type_index

    def actor_query(self, limit_actors: Optional[bool] = True) -> Tuple[str, Dict]:
        actor_query = _build_actor_query(
            filter=self._filter,
            team=self._team,
            filter_by_breakdown=self._filter.breakdown_values or (0,),
            selected_interval=self._filter.selected_interval,
        )

        return actor_query, {}


# Note: This class does not respect the entire flor from ActorBaseQuery because the result shape differs from other actor queries
class ClickhouseRetentionActorsByPeriod(ActorBaseQuery):
    _filter: RetentionFilter

    def __init__(self, team: Team, filter: RetentionFilter):
        super().__init__(team, filter)

    @cached_property
    def aggregation_group_type_index(self):
        return self._filter.aggregation_group_type_index

    def actors(self):
        """
        Creates a response of the form

        ```
        [
            {
                "person": {"distinct_id": ..., ...},
                "appearance_count": 3,
                "appearances": [1, 0, 1, 1, 0, 0]
            }
            ...
        ]
        ```

        where appearances values represent if the person was active in an
        interval, where the index of the list is the interval it refers to.
        """
        actor_query = _build_actor_query(
            filter=self._filter,
            team=self._team,
            filter_by_breakdown=(
                self._filter.breakdown_values or (self._filter.selected_interval,)
                if self._filter.selected_interval is not None
                else None
            ),
        )

        actor_appearances = [
            AppearanceRow(actor_id=str(row[0]), appearance_count=len(row[1]), appearances=row[1])
            for row in sync_execute(actor_query)
        ]

        _, serialized_actors = self.get_actors_from_result(
            [(actor_appearance.actor_id,) for actor_appearance in actor_appearances]
        )

        actors_lookup = {str(actor["id"]): actor for actor in serialized_actors}

        return [
            {
                "person": actors_lookup.get(actor.actor_id, {"id": actor.actor_id, "distinct_ids": []}),
                "appearances": [
                    1 if interval_number in actor.appearances else 0
                    for interval_number in range(self._filter.total_intervals - (self._filter.selected_interval or 0))
                ],
            }
            for actor in sorted(actor_appearances, key=lambda x: (x.appearance_count, x.actor_id), reverse=True)
        ]


def build_actor_activity_query(
    filter: RetentionFilter,
    team: Team,
    filter_by_breakdown: Optional[BreakdownValues] = None,
    selected_interval: Optional[int] = None,
    aggregate_users_by_distinct_id: Optional[bool] = None,
) -> str:
    """
    The retention actor query is used to retrieve something of the form:

        breakdown_values, intervals_from_base, actor_id

    We use actor here as an abstraction over the different types we can have aside from
    person_ids
    """
    returning_event_query = build_returning_event_query(
        filter=filter, team=team, aggregate_users_by_distinct_id=aggregate_users_by_distinct_id
    )

    target_event_query = build_target_event_query(
        filter=filter, team=team, aggregate_users_by_distinct_id=aggregate_users_by_distinct_id
    )

    all_params = {
        "period": filter.period.lower(),
        "breakdown_values": list(filter_by_breakdown) if filter_by_breakdown else None,
        "selected_interval": selected_interval,
    }

    query = substitute_params(RETENTION_BREAKDOWN_ACTOR_SQL, all_params).format(
        returning_event_query=returning_event_query, target_event_query=target_event_query,
    )

    return query


def _build_actor_query(
    filter: RetentionFilter,
    team: Team,
    filter_by_breakdown: Optional[BreakdownValues] = None,
    selected_interval: Optional[int] = None,
):
    actor_activity_query = build_actor_activity_query(
        filter=filter,
        team=team,
        filter_by_breakdown=filter_by_breakdown,
        selected_interval=selected_interval,
        aggregate_users_by_distinct_id=False,
    )

    actor_query_template = """
        SELECT
            actor_id,
            groupArray(actor_activity.intervals_from_base) AS appearances

        FROM ({actor_activity_query}) AS actor_activity

        GROUP BY actor_id

        -- make sure we have stable ordering/pagination
        -- NOTE: relies on ids being monotonic
        ORDER BY actor_id

        LIMIT 100
        OFFSET %(offset)s
    """

    actor_query = substitute_params(actor_query_template, {"offset": filter.offset}).format(
        actor_activity_query=actor_activity_query
    )

    return actor_query
