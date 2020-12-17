from typing import Any, Dict, Optional

from django.http.request import HttpRequest

from posthog.constants import INSIGHT_PATHS
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import DateMixin, InsightMixin, IntervalMixin
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
    InsightMixin,
    DateMixin,
    BaseFilter,
):
    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        if data:
            data["insight"] = INSIGHT_PATHS
        else:
            data = {"insight": INSIGHT_PATHS}
        super().__init__(data, request)
