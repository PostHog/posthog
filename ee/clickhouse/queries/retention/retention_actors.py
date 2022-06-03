from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.retention.actors_query import RetentionActors, RetentionActorsByPeriod


class ClickhouseRetentionActors(RetentionActors):
    @cached_property
    def aggregation_group_type_index(self):
        return self._filter.aggregation_group_type_index


# Note: This class does not respect the entire flor from ActorBaseQuery because the result shape differs from other actor queries
class ClickhouseRetentionActorsByPeriod(RetentionActorsByPeriod):
    @cached_property
    def aggregation_group_type_index(self):
        return self._filter.aggregation_group_type_index
