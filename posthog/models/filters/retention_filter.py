import json
from typing import Any, Dict, List, Optional

from rest_framework.request import Request

from posthog.constants import INSIGHT_RETENTION, SELECTED_INTERVAL
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import (
    BreakdownMixin,
    DisplayDerivedMixin,
    FilterTestAccountsMixin,
    InsightMixin,
    OffsetMixin,
)
from posthog.models.filters.mixins.funnel import FunnelCorrelationMixin
from posthog.models.filters.mixins.groups import GroupsAggregationMixin
from posthog.models.filters.mixins.property import PropertyMixin
from posthog.models.filters.mixins.retention import EntitiesDerivedMixin, RetentionDateDerivedMixin, RetentionTypeMixin, SelectedIntervalMixin
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
    GroupsAggregationMixin,
    FunnelCorrelationMixin,  # Typing pain because ColumnOptimizer expects a uniform filter
    # TODO: proper fix for EventQuery abstraction, make filters uniform
    SimplifyFilterMixin,
    BaseFilter,
):
    def __init__(self, data: Dict[str, Any] = {}, request: Optional[Request] = None, **kwargs) -> None:
        data["insight"] = INSIGHT_RETENTION
        super().__init__(data, request, **kwargs)

    @cached_property
    def breakdown_values(self) -> List[str]:
        raw_value = self._data.get("breakdown_values", None)
        if isinstance(raw_value, str):
            return json.loads(raw_value)
        return list(raw_value) if raw_value else None

    @include_dict
    def breakdown_values_to_dict(self):
        return {"breakdown_values": self.breakdown_values} if self.breakdown_values else {}


class RetentionPeopleRequest(RetentionFilter):
    @cached_property
    def selected_interval(self) -> Optional[int]:
        return int(raw) if (raw := self._data.get(SELECTED_INTERVAL)) else None

    @include_dict
    def selected_interval_to_dict(self):
        return {"selected_interval": self.selected_interval} if self.selected_interval else {}


