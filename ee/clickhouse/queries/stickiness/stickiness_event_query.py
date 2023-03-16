from posthog.models.group.util import get_aggregation_target_field
from posthog.queries.stickiness.stickiness_event_query import StickinessEventsQuery
from posthog.utils import PersonOnEventsMode


class ClickhouseStickinessEventsQuery(StickinessEventsQuery):
    def aggregation_target(self):
        return get_aggregation_target_field(
            self._entity.math_group_type_index,
            self.EVENT_TABLE_ALIAS,
            f"{self.DISTINCT_ID_TABLE_ALIAS if self._person_on_events_mode == PersonOnEventsMode.DISABLED else self.EVENT_TABLE_ALIAS}.person_id",
        )
