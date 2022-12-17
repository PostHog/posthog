from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import DateMixin, EntitiesMixin
from posthog.models.filters.mixins.groups import GroupsAggregationMixin
from posthog.models.filters.mixins.property import PropertyMixin


class PropertiesTimelineFilter(
    DateMixin,
    EntitiesMixin,
    PropertyMixin,
    GroupsAggregationMixin,
    BaseFilter,
):
    pass
