from typing import Dict, List, Optional, Tuple, Union

from ee.clickhouse.materialized_columns.columns import ColumnName
from ee.clickhouse.queries.column_optimizer import EnterpriseColumnOptimizer
from ee.clickhouse.queries.groups_join_query import GroupsJoinQuery
from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.property import PropertyName
from posthog.models.team import Team
from posthog.queries.event_query.event_query import EventQuery
from posthog.utils import PersonOnEventsMode


class EnterpriseEventQuery(EventQuery):
    _column_optimizer: EnterpriseColumnOptimizer

    def __init__(
        self,
        filter: Union[
            Filter,
            PathFilter,
            RetentionFilter,
            StickinessFilter,
            SessionRecordingsFilter,
            PropertiesTimelineFilter,
        ],
        team: Team,
        round_interval=False,
        should_join_distinct_ids=False,
        should_join_persons=False,
        # Extra events/person table columns to fetch since parent query needs them
        extra_fields: List[ColumnName] = [],
        extra_event_properties: List[PropertyName] = [],
        extra_person_fields: List[ColumnName] = [],
        override_aggregate_users_by_distinct_id: Optional[bool] = None,
        person_on_events_mode: PersonOnEventsMode = PersonOnEventsMode.DISABLED,
        **kwargs,
    ) -> None:
        super().__init__(
            filter=filter,
            team=team,
            round_interval=round_interval,
            should_join_distinct_ids=should_join_distinct_ids,
            should_join_persons=should_join_persons,
            extra_fields=extra_fields,
            extra_event_properties=extra_event_properties,
            extra_person_fields=extra_person_fields,
            override_aggregate_users_by_distinct_id=override_aggregate_users_by_distinct_id,
            person_on_events_mode=person_on_events_mode,
            **kwargs,
        )

        self._column_optimizer = EnterpriseColumnOptimizer(self._filter, self._team_id)

    def _get_groups_query(self) -> Tuple[str, Dict]:
        if isinstance(self._filter, PropertiesTimelineFilter):
            raise Exception("Properties Timeline never needs groups query")
        return GroupsJoinQuery(
            self._filter,
            self._team_id,
            self._column_optimizer,
            person_on_events_mode=self._person_on_events_mode,
        ).get_join_query()
