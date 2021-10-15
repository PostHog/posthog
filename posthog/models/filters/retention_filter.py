from typing import Any, Dict, Optional

from rest_framework.request import Request

from posthog.constants import INSIGHT_RETENTION
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import (
    BreakdownMixin,
    BreakdownTypeMixin,
    DisplayDerivedMixin,
    FilterTestAccountsMixin,
    InsightMixin,
    OffsetMixin,
)
from posthog.models.filters.mixins.funnel import FunnelCorrelationMixin
from posthog.models.filters.mixins.property import PropertyMixin
from posthog.models.filters.mixins.retention import EntitiesDerivedMixin, RetentionDateDerivedMixin, RetentionTypeMixin
from posthog.models.filters.mixins.simplify import SimplifyFilterMixin

RETENTION_DEFAULT_INTERVALS = 11


class RetentionFilter(
    RetentionTypeMixin,
    EntitiesDerivedMixin,
    RetentionDateDerivedMixin,
    PropertyMixin,
    DisplayDerivedMixin,
    FilterTestAccountsMixin,
    BreakdownMixin,
    BreakdownTypeMixin,
    InsightMixin,
    OffsetMixin,
    FunnelCorrelationMixin,  # Typing pain because ColumnOptimizer expects a uniform filter
    # TODO: proper fix for EventQuery abstraction, make filters uniform
    SimplifyFilterMixin,
    BaseFilter,
):
    def __init__(self, data: Dict[str, Any] = {}, request: Optional[Request] = None, **kwargs) -> None:
        data["insight"] = INSIGHT_RETENTION
        super().__init__(data, request, **kwargs)
