from ee.clickhouse.models.group import get_aggregation_target_field
from posthog.queries.stickiness.stickiness_event_query import StickinessEventsQuery


class ClickhouseStickinessEventsQuery(StickinessEventsQuery):
    def aggregation_target(self):
        return get_aggregation_target_field(
            self._entity.math_group_type_index,
            self.EVENT_TABLE_ALIAS,
            f"{self.DISTINCT_ID_TABLE_ALIAS if not self._using_person_on_events else self.EVENT_TABLE_ALIAS}.person_id",
        )
