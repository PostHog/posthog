from typing import Dict, Tuple

from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.stickiness.stickiness_event_query import StickinessEventsQuery
from posthog.models.entity import Entity
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team


class ClickhouseStickinessActors(ActorBaseQuery):
    entity: Entity
    _filter: StickinessFilter

    def __init__(self, team: Team, entity: Entity, filter: StickinessFilter):
        super().__init__(team, filter, entity)

    @cached_property
    def is_aggregating_by_groups(self) -> bool:
        return self.entity.math == "unique_group"

    def actor_query(self) -> Tuple[str, Dict]:
        events_query, event_params = StickinessEventsQuery(
            entity=self.entity, filter=self._filter, team_id=self._team.pk
        ).get_query()

        return (
            f"""
        SELECT DISTINCT aggregation_target FROM ({events_query}) WHERE num_intervals = %(stickiness_day)s
        {'LIMIT %(limit)s' if self._filter.limit > 0 else ''}
        {'OFFSET %(offset)s' if self._filter.limit > 0 else ''}
        """,
            {
                **event_params,
                "stickiness_day": self._filter.selected_interval,
                "offset": self._filter.offset,
                "limit": self._filter.limit,
            },
        )
