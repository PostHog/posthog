from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import DateMixin, IntervalMixin, PropertyMixin
from posthog.models.filters.mixins.paths import ComparatorMixin, PropTypeMixin, StartPointMixin, TargetEventMixin


class PathFilter(
    StartPointMixin,
    TargetEventMixin,
    ComparatorMixin,
    PropTypeMixin,
    DateMixin,
    PropertyMixin,
    IntervalMixin,
    BaseFilter,
):
    pass
