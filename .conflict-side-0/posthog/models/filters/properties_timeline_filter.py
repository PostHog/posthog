from .base_filter import BaseFilter
from .mixins.common import BreakdownMixin, DisplayDerivedMixin, EntitiesMixin
from .mixins.groups import GroupsAggregationMixin
from .mixins.interval import IntervalMixin
from .mixins.property import PropertyMixin


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
