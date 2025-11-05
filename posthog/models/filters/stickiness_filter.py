from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional, Union

from django.db.models.functions.datetime import TruncDay, TruncHour, TruncMonth, TruncWeek

from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.constants import INSIGHT_STICKINESS

from .base_filter import BaseFilter
from .mixins.common import (
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
from .mixins.property import PropertyMixin
from .mixins.simplify import SimplifyFilterMixin
from .mixins.stickiness import SelectedIntervalMixin, TotalIntervalsDerivedMixin

if TYPE_CHECKING:
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
    team: "Team"

    def __init__(
        self,
        data: Optional[dict[str, Any]] = None,
        request: Optional[Request] = None,
        **kwargs,
    ) -> None:
        if data:
            data["insight"] = INSIGHT_STICKINESS
        else:
            data = {"insight": INSIGHT_STICKINESS}
        super().__init__(data, request, **kwargs)
        team: Optional[Team] = kwargs.get("team", None)
        if not team:
            raise ValidationError("Team must be provided to stickiness filter")
        self.team = team
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
