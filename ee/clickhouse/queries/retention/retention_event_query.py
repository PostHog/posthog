from posthog.models.group.util import get_aggregation_target_field
from posthog.queries.retention.retention_events_query import RetentionEventsQuery
from posthog.utils import PersonOnEventsMode


class ClickhouseRetentionEventsQuery(RetentionEventsQuery):
    def target_field(self) -> str:
        if self._aggregate_users_by_distinct_id and not self._filter.aggregation_group_type_index:
            return f"{self.EVENT_TABLE_ALIAS}.distinct_id as target"
        else:
            return "{} as target".format(
                get_aggregation_target_field(
                    self._filter.aggregation_group_type_index,
                    self.EVENT_TABLE_ALIAS,
                    f"{self.DISTINCT_ID_TABLE_ALIAS if self._person_on_events_mode == PersonOnEventsMode.DISABLED else self.EVENT_TABLE_ALIAS}.person_id",
                )
            )
