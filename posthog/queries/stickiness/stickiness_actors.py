from typing import Dict, Optional, Tuple

from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from posthog.models.entity import Entity
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team
from posthog.queries.stickiness.stickiness_event_query import StickinessEventsQuery


class StickinessActors(ActorBaseQuery):
    entity: Entity
    _filter: StickinessFilter

    def __init__(self, team: Team, entity: Entity, filter: StickinessFilter, **kwargs):
        super().__init__(team, filter, entity, **kwargs)

    @cached_property
    def aggregation_group_type_index(self):
        return None

    def actor_query(self, limit_actors: Optional[bool] = True) -> Tuple[str, Dict]:
        events_query, event_params = StickinessEventsQuery(
            entity=self.entity,
            filter=self._filter,
            team=self._team,
            using_person_on_events=self._team.actor_on_events_querying_enabled,
        ).get_query()

        return (
            f"""
        SELECT DISTINCT aggregation_target AS actor_id FROM ({events_query}) WHERE num_intervals = %(stickiness_day)s
        {"LIMIT %(limit)s" if limit_actors else ""}
        {"OFFSET %(offset)s" if limit_actors else ""}

        SETTINGS optimize_move_to_prewhere = 0
        """,
            {
                **event_params,
                "stickiness_day": self._filter.selected_interval,
                "offset": self._filter.offset,
                "limit": self._filter.limit,
            },
        )
