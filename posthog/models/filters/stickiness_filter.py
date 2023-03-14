from typing import Any, Callable, Dict, Optional, Union

from django.db.models.functions.datetime import TruncDay, TruncHour, TruncMonth, TruncWeek
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import (
    ClientQueryIdMixin,
    CompareMixin,
    EntitiesMixin,
    EntityIdMixin,
    EntityMathMixin,
    EntityOrderMixin,
    EntityTypeMixin,
    FilterTestAccountsMixin,
    InsightMixin,
    LimitMixin,
    OffsetMixin,
    SampleMixin,
    SearchMixin,
    ShownAsMixin,
)
from posthog.models.filters.mixins.property import PropertyMixin
from posthog.models.filters.mixins.simplify import SimplifyFilterMixin
from posthog.models.filters.mixins.stickiness import SelectedIntervalMixin, TotalIntervalsDerivedMixin
from posthog.models.team import Team


class StickinessFilter(
    TotalIntervalsDerivedMixin,
    EntitiesMixin,
    EntityIdMixin,
    EntityTypeMixin,
    EntityOrderMixin,
    EntityMathMixin,
    SelectedIntervalMixin,
    SearchMixin,
    PropertyMixin,
    FilterTestAccountsMixin,
    OffsetMixin,
    CompareMixin,
    ShownAsMixin,
    InsightMixin,
    SimplifyFilterMixin,
    LimitMixin,
    ClientQueryIdMixin,
    SampleMixin,
    BaseFilter,
):
    get_earliest_timestamp: Optional[Callable]
    team: Team

    def __init__(
        self, team: "Team", data: Optional[Dict[str, Any]] = None, request: Optional[Request] = None, **kwargs
    ) -> None:
        self.team = team
        super().__init__(team, data, request, **kwargs)
        self.get_earliest_timestamp = kwargs.get("get_earliest_timestamp", None)

    def trunc_func(self, field_name: str) -> Union[TruncHour, TruncDay, TruncWeek, TruncMonth]:
        if self.interval == "hour":
            return TruncHour(field_name)
        elif self.interval == "day":
            return TruncDay(field_name)
        elif self.interval == "week":
            return TruncWeek(field_name)
        elif self.interval == "month":
            return TruncMonth(field_name)
        else:
            raise ValidationError(f"{self.interval} not supported")
