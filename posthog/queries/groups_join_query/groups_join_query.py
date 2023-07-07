from typing import Dict, Optional, Tuple, Union

from posthog.models import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.queries.column_optimizer.column_optimizer import ColumnOptimizer
from posthog.utils import PersonOnEventsMode


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
        person_on_events_mode: PersonOnEventsMode = PersonOnEventsMode.DISABLED,
    ) -> None:
        self._filter = filter
        self._team_id = team_id
        self._column_optimizer = column_optimizer or ColumnOptimizer(self._filter, self._team_id)
        self._join_key = join_key
        self._person_on_events_mode = person_on_events_mode

    def get_join_query(self) -> Tuple[str, Dict]:
        return "", {}
