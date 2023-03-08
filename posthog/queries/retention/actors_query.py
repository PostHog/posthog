import dataclasses
from typing import Any, Dict, List, Optional, Tuple

from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.team import Team
from posthog.queries.actor_base_query import ActorBaseQuery
from posthog.queries.insight import insight_sync_execute
from posthog.queries.retention.retention_events_query import RetentionEventsQuery
from posthog.queries.retention.sql import RETENTION_BREAKDOWN_ACTOR_SQL
from posthog.queries.retention.types import BreakdownValues


@dataclasses.dataclass
class AppearanceRow:
    """
    Container for the rows of the "Appearance count" query.
    """

    actor_id: str
    appearance_count: int
    # This is actually the number of days from first event to the current event.
    appearances: List[float]


# Note: This class does not respect the entire flor from ActorBaseQuery because the result shape differs from other actor queries
class RetentionActorsByPeriod(ActorBaseQuery):
    _filter: RetentionFilter
    _retention_events_query = RetentionEventsQuery

    QUERY_TYPE = "retention_actors_by_period"

    def __init__(self, team: Team, filter: RetentionFilter):
        super().__init__(team, filter)

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
        actor_query, actor_query_params = _build_actor_query(
            filter=self._filter,
            team=self._team,
            filter_by_breakdown=(
                self._filter.breakdown_values or (self._filter.selected_interval,)
                if self._filter.selected_interval is not None
                else None
            ),
            retention_events_query=self._retention_events_query,
        )

        results = insight_sync_execute(
            actor_query,
            {**actor_query_params, **self._filter.hogql_context.values},
            query_type="retention_actors",
            filter=self._filter,
        )
        actor_appearances = [
            AppearanceRow(actor_id=str(row[0]), appearance_count=len(row[1]), appearances=row[1]) for row in results
        ]

        _, serialized_actors = self.get_actors_from_result(
            [(actor_appearance.actor_id,) for actor_appearance in actor_appearances]
        )

        actors_lookup = {str(actor["id"]): actor for actor in serialized_actors}

        return [
            {
                "person": actors_lookup[actor.actor_id],
                "appearances": [
                    1 if interval_number in actor.appearances else 0
                    for interval_number in range(self._filter.total_intervals - (self._filter.selected_interval or 0))
                ],
            }
            for actor in actor_appearances
            if actor.actor_id in actors_lookup
        ], len(actor_appearances)


def build_actor_activity_query(
    filter: RetentionFilter,
    team: Team,
    filter_by_breakdown: Optional[BreakdownValues] = None,
    selected_interval: Optional[int] = None,
    aggregate_users_by_distinct_id: Optional[bool] = None,
    retention_events_query=RetentionEventsQuery,
) -> Tuple[str, Dict[str, Any]]:
    from posthog.queries.retention import build_returning_event_query, build_target_event_query

    """
    The retention actor query is used to retrieve something of the form:

        breakdown_values, intervals_from_base, actor_id

    We use actor here as an abstraction over the different types we can have aside from
    person_ids
    """
    returning_event_query, returning_event_query_params = build_returning_event_query(
        filter=filter,
        team=team,
        aggregate_users_by_distinct_id=aggregate_users_by_distinct_id,
        using_person_on_events=team.person_on_events_querying_enabled,
        retention_events_query=retention_events_query,
    )

    target_event_query, target_event_query_params = build_target_event_query(
        filter=filter,
        team=team,
        aggregate_users_by_distinct_id=aggregate_users_by_distinct_id,
        using_person_on_events=team.person_on_events_querying_enabled,
        retention_events_query=retention_events_query,
    )

    all_params = {
        "period": filter.period.lower(),
        "breakdown_values": list(filter_by_breakdown) if filter_by_breakdown else None,
        "selected_interval": selected_interval,
        **returning_event_query_params,
        **target_event_query_params,
    }

    query = RETENTION_BREAKDOWN_ACTOR_SQL.format(
        returning_event_query=returning_event_query, target_event_query=target_event_query
    )

    return query, all_params


def _build_actor_query(
    filter: RetentionFilter,
    team: Team,
    filter_by_breakdown: Optional[BreakdownValues] = None,
    selected_interval: Optional[int] = None,
    retention_events_query=RetentionEventsQuery,
) -> Tuple[str, Dict[str, Any]]:

    actor_activity_query, actor_activity_query_params = build_actor_activity_query(
        filter=filter,
        team=team,
        filter_by_breakdown=filter_by_breakdown,
        selected_interval=selected_interval,
        aggregate_users_by_distinct_id=False,
        retention_events_query=retention_events_query,
    )

    params = {"offset": filter.offset, "limit": filter.limit or 100, **actor_activity_query_params}
    actor_query_template = """
        SELECT
            actor_id,
            groupArray(actor_activity.intervals_from_base) AS appearances

        FROM ({actor_activity_query}) AS actor_activity

        GROUP BY actor_id

        -- make sure we have stable ordering/pagination
        -- NOTE: relies on ids being monotonic
        ORDER BY length(appearances) DESC, actor_id

        LIMIT %(limit)s
        OFFSET %(offset)s
    """

    actor_query = actor_query_template.format(actor_activity_query=actor_activity_query)

    return actor_query, params
