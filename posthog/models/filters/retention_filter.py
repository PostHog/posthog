import datetime
import json
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.http import HttpRequest

from posthog.constants import (
    INSIGHT_RETENTION,
    PERIOD,
    RETENTION_RECURRING,
    RETENTION_TYPE,
    SELECTED_INTERVAL,
    TARGET_ENTITY,
    TOTAL_INTERVALS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.models.entity import Entity
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.filter import Filter
from posthog.models.filters.mixins.common import (
    BreakdownMixin,
    BreakdownTypeMixin,
    DisplayDerivedMixin,
    FilterTestAccountsMixin,
    InsightMixin,
    IntervalMixin,
    OffsetMixin,
)
from posthog.models.filters.mixins.property import PropertyMixin
from posthog.models.filters.mixins.retention import (
    EntitiesDerivedMixin,
    PeriodMixin,
    RetentionDateDerivedMixin,
    RetentionTypeMixin,
    SelectedIntervalMixin,
    TotalIntervalsMixin,
)

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
    BaseFilter,
):
    def __init__(self, data: Dict[str, Any] = {}, request: Optional[HttpRequest] = None, **kwargs) -> None:
        data["insight"] = INSIGHT_RETENTION
        super().__init__(data, request, **kwargs)
