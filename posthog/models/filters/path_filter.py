from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import DateMixin, IntervalMixin
from posthog.models.filters.mixins.paths import ComparatorMixin, PropTypeMixin, StartPointMixin, TargetEventMixin
from posthog.models.filters.mixins.property import PropertyMixin


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
