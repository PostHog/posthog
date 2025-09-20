from typing import Optional

from posthog.models.filters.lifecycle_filter import LifecycleFilter
from posthog.queries.actor_base_query import ActorBaseQuery
from posthog.queries.trends.lifecycle import LifecycleEventQuery
from posthog.queries.trends.sql import LIFECYCLE_PEOPLE_SQL


class LifecycleActors(ActorBaseQuery):
    event_query_class = LifecycleEventQuery
    _filter: LifecycleFilter

    QUERY_TYPE = "lifecycle"

    def actor_query(self, limit_actors: Optional[bool] = True) -> tuple[str, dict]:
        events_query, event_params = self.event_query_class(
            filter=self._filter,
            team=self._team,
            person_on_events_mode=self._team.person_on_events_mode,
        ).get_query()

        lifecycle_type = self._filter.lifecycle_type
        target_date = self._filter.target_date

        return (
            LIFECYCLE_PEOPLE_SQL.format(
                events_query=events_query,
                limit=f'{"LIMIT %(limit)s" if limit_actors else ""}',
                offset=f'{"OFFSET %(offset)s" if limit_actors else ""}',
            ),
            {
                **event_params,
                **self._filter.hogql_context.values,
                "offset": self._filter.offset,
                "limit": self._filter.limit,
                "status": lifecycle_type,
                "target_date": target_date,
            },
        )
