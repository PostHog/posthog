from typing import Dict, Tuple

from ee.clickhouse.queries.groups_join_query import GroupsJoinQuery
from posthog.queries.event_query import EventQuery


class EE_EventQuery(EventQuery):
    def _get_groups_query(self) -> Tuple[str, Dict]:
        return GroupsJoinQuery(self._filter, self._team_id, self._column_optimizer).get_join_query()
