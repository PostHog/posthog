from typing import Any, Callable, Dict, Optional, Union

from django.db.models.functions.datetime import TruncDay, TruncHour, TruncMinute, TruncMonth, TruncWeek
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import (
    CompareMixin,
    EntitiesMixin,
    FilterTestAccountsMixin,
    InsightMixin,
    LimitMixin,
    OffsetMixin,
    ShownAsMixin,
)
from posthog.models.filters.mixins.property import PropertyMixin
from posthog.models.filters.mixins.simplify import SimplifyFilterMixin
from posthog.models.filters.mixins.stickiness import SelectedIntervalMixin, TotalIntervalsDerivedMixin
from posthog.models.team import Team


class StickinessFilter(
    TotalIntervalsDerivedMixin,
    EntitiesMixin,
    SelectedIntervalMixin,
    PropertyMixin,
    FilterTestAccountsMixin,
    OffsetMixin,
    CompareMixin,
    ShownAsMixin,
    InsightMixin,
    SimplifyFilterMixin,
    LimitMixin,
    BaseFilter,
):
    get_earliest_timestamp: Optional[Callable]
    team: Team

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[Request] = None, **kwargs) -> None:
        super().__init__(data, request, **kwargs)
        team: Optional[Team] = kwargs.get("team", None)
        if not team:
            raise ValidationError("Team must be provided to stickiness filter")
        self.team = team
        self.get_earliest_timestamp = kwargs.get("get_earliest_timestamp", None)

    def trunc_func(self, field_name: str) -> Union[TruncMinute, TruncHour, TruncDay, TruncWeek, TruncMonth]:
        if self.interval == "minute":
            return TruncMinute(field_name)
        elif self.interval == "hour":
            return TruncHour(field_name)
        elif self.interval == "day":
            return TruncDay(field_name)
        elif self.interval == "week":
            return TruncWeek(field_name)
        elif self.interval == "month":
            return TruncMonth(field_name)
        else:
            raise ValidationError(f"{self.interval} not supported")
