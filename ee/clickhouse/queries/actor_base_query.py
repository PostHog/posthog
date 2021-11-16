from typing import Dict, Optional, Tuple

from ee.clickhouse.client import sync_execute
from posthog.models import Entity, Filter, Team


class ActorBaseQuery:
    aggregating_by_groups = False

    def __init__(self, team: Team, filter: Filter, entity: Optional[Entity] = None):
        self.team = team
        self.entity = entity
        self.filter = filter

        if self.entity and self.entity.math == "unique_group":
            self.aggregating_by_groups = True

    def groups_query(self) -> Tuple[str, Dict]:
        raise NotImplementedError()

    def people_query(self) -> Tuple[str, Dict]:
        raise NotImplementedError()

    def get_query(self) -> Tuple[str, Dict]:
        if self.aggregating_by_groups:
            query, params = self.groups_query()
            return query, params
        else:
            query, params = self.people_query()
            return query, params

    def get_actors(self):
        query, params = self.get_query()
        return sync_execute(query, params)
