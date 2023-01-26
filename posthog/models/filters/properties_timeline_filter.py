from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import BreakdownMixin, DisplayDerivedMixin, EntitiesMixin
from posthog.models.filters.mixins.groups import GroupsAggregationMixin
from posthog.models.filters.mixins.interval import IntervalMixin
from posthog.models.filters.mixins.property import PropertyMixin


class PropertiesTimelineFilter(
    IntervalMixin,
    EntitiesMixin,
    PropertyMixin,
    GroupsAggregationMixin,
    DisplayDerivedMixin,
    BreakdownMixin,
    BaseFilter,
):
    pass
