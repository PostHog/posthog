from datetime import datetime
from typing import Any, Callable, Dict, Optional, Union

from django.db.models.expressions import Value
from django.db.models.functions.datetime import TruncDay, TruncHour, TruncMinute, TruncMonth, TruncWeek, TruncYear
from django.http import HttpRequest
from django.utils import timezone

from posthog.constants import ENTITY_ID, INTERVAL, STICKINESS_DAYS, TYPE
from posthog.models.entity import Entity
from posthog.models.event import Event
from posthog.models.filters.filter import Filter
from posthog.models.team import Team
from posthog.utils import relative_date_parse


class StickinessFilter(Filter):
    num_intervals: int
    date_from: datetime
    date_to: datetime
    interval: str = "Day"
    entityId: Optional[str]
    type: Optional[str]
    stickiness_days: int

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        super().__init__(data, request)
        if request:
            data = {
                **request.GET.dict(),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")

        team: Optional[Team] = kwargs.get("team", None)
        if not team:
            raise ValueError("Team must be provided to stickiness filter")

        if self._date_from == "all":
            get_earliest_timestamp: Optional[Callable] = kwargs.get("get_earliest_timestamp", None)
            if not get_earliest_timestamp:
                raise ValueError("Callable must be provided when date filtering is all time")

            self._date_from = get_earliest_timestamp(team_id=team.pk)

        if not self._date_from:
            self._date_from = relative_date_parse("-7d")

        if not self._date_to:
            self._date_to = timezone.now().isoformat()

        self.stickiness_days = int(data.get(STICKINESS_DAYS, "0"))
        self.interval = data.get(INTERVAL, "day").lower()
        self.entityId = data.get(ENTITY_ID, None)
        self.type = data.get(TYPE, None)

        total_seconds = (self.date_to - self.date_from).total_seconds()
        if self.interval == "minute":
            self.num_intervals = int(divmod(total_seconds, 60)[0])
        elif self.interval == "hour":
            self.num_intervals = int(divmod(total_seconds, 3600)[0])
        elif self.interval == "day":
            self.num_intervals = int(divmod(total_seconds, 86400)[0])
            self._date_to = self.date_to.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        elif self.interval == "week":
            self.num_intervals = (self.date_to - self.date_from).days // 7
            self._date_to = self.date_to.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        elif self.interval == "month":
            self.num_intervals = (self.date_to.year - self.date_from.year) + (self.date_to.month - self.date_from.month)
            self._date_to = self.date_to.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        else:
            raise ValueError(f"{self.interval} not supported")
        self.num_intervals += 2

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

    @property
    def target_entity(self) -> Entity:
        if self.entities:
            return self.entities[0]
        elif self.entityId and self.type:
            return Entity({"id": self.entityId, "type": self.type})
        else:
            raise ValueError("An entity must be provided for stickiness target entity to be determined")

    def to_dict(self) -> Dict[str, Any]:
        common_vals = super().to_dict()
        full_dict = {**common_vals, STICKINESS_DAYS: self.stickiness_days, ENTITY_ID: self.entityId, TYPE: self.type}
        return full_dict
