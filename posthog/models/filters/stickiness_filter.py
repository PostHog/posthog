import json
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Union

from django.db.models.expressions import Value
from django.db.models.functions.datetime import TruncDay, TruncHour, TruncMinute, TruncMonth, TruncWeek, TruncYear
from django.http import HttpRequest
from django.utils import timezone

from posthog.constants import INTERVAL, STICKINESS_DAYS
from posthog.models.entity import Entity
from posthog.models.event import Event
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.filter import Filter
from posthog.models.filters.mixins.common import CompareMixin, DateMixin, IntervalMixin, OffsetMixin, ShownAsMixin
from posthog.models.filters.mixins.property import PropertyMixin
from posthog.models.filters.mixins.stickiness import (
    EntityIdMixin,
    EntityTypeMixin,
    SelectedIntervalMixin,
    TargetEntityDerivedMixin,
    TotalIntervalsDerivedMixin,
)
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property import Property
from posthog.models.team import Team
from posthog.utils import relative_date_parse


class StickinessFilter(
    TotalIntervalsDerivedMixin,
    TargetEntityDerivedMixin,
    SelectedIntervalMixin,
    PropertyMixin,
    OffsetMixin,
    CompareMixin,
    ShownAsMixin,
    DateMixin,
    BaseFilter,
):
    get_earliest_timestamp: Callable
    team: Team

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        super().__init__(data, request)
        team: Optional[Team] = kwargs.get("team", None)
        if not team:
            raise ValueError("Team must be provided to stickiness filter")
        self.team = team
        get_earliest_timestamp: Optional[Callable] = kwargs.get("get_earliest_timestamp", None)
        if not get_earliest_timestamp:
            raise ValueError("Callable must be provided when date filtering is all time")
        self.get_earliest_timestamp = get_earliest_timestamp  # type: ignore

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
            raise ValueError(f"{self.interval} not supported")
