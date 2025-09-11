from posthog.models.group.util import get_aggregation_target_field
from posthog.queries.stickiness.stickiness_event_query import StickinessEventsQuery


class ClickhouseStickinessEventsQuery(StickinessEventsQuery):
    def aggregation_target(self):
        return get_aggregation_target_field(
            self._entity.math_group_type_index,
            self.EVENT_TABLE_ALIAS,
            self._person_id_alias,
        )
