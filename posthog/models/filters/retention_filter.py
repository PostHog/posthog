import json
from typing import Any, Dict, Optional, Tuple, Union

from rest_framework.request import Request

from posthog.constants import INSIGHT_RETENTION
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import (
    BreakdownMixin,
    ClientQueryIdMixin,
    DisplayDerivedMixin,
    FilterTestAccountsMixin,
    InsightMixin,
    LimitMixin,
    OffsetMixin,
    SampleMixin,
)
from posthog.models.filters.mixins.funnel import FunnelCorrelationMixin
from posthog.models.filters.mixins.groups import GroupsAggregationMixin
from posthog.models.filters.mixins.property import PropertyMixin
from posthog.models.filters.mixins.retention import EntitiesDerivedMixin, RetentionDateDerivedMixin, RetentionTypeMixin
from posthog.models.filters.mixins.simplify import SimplifyFilterMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict

RETENTION_DEFAULT_INTERVALS = 11


class RetentionFilter(
    RetentionTypeMixin,
    EntitiesDerivedMixin,
    RetentionDateDerivedMixin,
    PropertyMixin,
    DisplayDerivedMixin,
    FilterTestAccountsMixin,
    BreakdownMixin,
    InsightMixin,
    OffsetMixin,
    LimitMixin,
    GroupsAggregationMixin,
    FunnelCorrelationMixin,  # Typing pain because ColumnOptimizer expects a uniform filter
    # TODO: proper fix for EventQuery abstraction, make filters uniform
    ClientQueryIdMixin,
    SimplifyFilterMixin,
    BaseFilter,
    SampleMixin,
):
    def __init__(self, data: Dict[str, Any] = {}, request: Optional[Request] = None, **kwargs) -> None:
        data["insight"] = INSIGHT_RETENTION
        super().__init__(data, request, **kwargs)

    @cached_property
    def breakdown_values(self) -> Optional[Tuple[Union[str, int], ...]]:
        raw_value = self._data.get("breakdown_values", None)
        if raw_value is None:
            return None

        if isinstance(raw_value, str):
            return tuple(json.loads(raw_value))

        return tuple(raw_value)

    @include_dict
    def breakdown_values_to_dict(self):
        return {"breakdown_values": self.breakdown_values} if self.breakdown_values else {}
