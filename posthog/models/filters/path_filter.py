from posthog.models.filters.base_filter import BaseFilter, SerializerWithDateMixin
from posthog.models.filters.mixins.common import DateMixin, IntervalMixin
from posthog.models.filters.mixins.paths import (
    ComparatorDerivedMixin,
    PropTypeDerivedMixin,
    StartPointMixin,
    TargetEventDerivedMixin,
)
from posthog.models.filters.mixins.property import PropertyMixin


class PathFilter(
    StartPointMixin,
    TargetEventDerivedMixin,
    ComparatorDerivedMixin,
    PropTypeDerivedMixin,
    PropertyMixin,
    IntervalMixin,
    SerializerWithDateMixin,
    BaseFilter,
):
    pass
