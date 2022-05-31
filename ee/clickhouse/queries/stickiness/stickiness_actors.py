from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.stickiness.stickiness_actors import StickinessActors


class ClickhouseStickinessActors(StickinessActors):
    @cached_property
    def aggregation_group_type_index(self):
        if self.entity.math == "unique_group":
            return self.entity.math_group_type_index
        return None
