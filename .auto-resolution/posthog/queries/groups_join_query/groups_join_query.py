from typing import Optional, Union

from posthog.schema import PersonsOnEventsMode

from posthog.models import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.queries.column_optimizer.column_optimizer import ColumnOptimizer
from posthog.queries.util import alias_poe_mode_for_legacy


class GroupsJoinQuery:
    """
    Query class responsible for joining with `groups` clickhouse table based on filters
    """

    _filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter]
    _team_id: int
    _column_optimizer: ColumnOptimizer

    def __init__(
        self,
        filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter],
        team_id: int,
        column_optimizer: Optional[ColumnOptimizer] = None,
        join_key: Optional[str] = None,
        person_on_events_mode: PersonsOnEventsMode = PersonsOnEventsMode.DISABLED,
    ) -> None:
        self._filter = filter
        self._team_id = team_id
        self._column_optimizer = column_optimizer or ColumnOptimizer(self._filter, self._team_id)
        self._join_key = join_key
        self._person_on_events_mode = alias_poe_mode_for_legacy(person_on_events_mode)

    def get_join_query(self) -> tuple[str, dict]:
        return "", {}
