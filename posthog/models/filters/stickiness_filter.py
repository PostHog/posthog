from datetime import datetime
from typing import Any, Dict, Optional, Union

from django.db.models.functions.datetime import TruncDay, TruncHour, TruncMinute, TruncMonth, TruncWeek, TruncYear
from django.http import HttpRequest
from django.utils import timezone

from posthog.constants import PERIOD
from posthog.models.event import Event
from posthog.models.filters.filter import Filter
from posthog.models.team import Team
from posthog.utils import relative_date_parse


class StickinessFilter(Filter):
    num_intervals: int
    date_from: datetime
    date_to: datetime
    period: str = "Day"

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
            return (
                Event.objects.filter(team_id=team.pk)
                .order_by("timestamp")[0]
                .timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                .isoformat()
            )
        elif not self._date_from:
            self._date_from = relative_date_parse("-7d")

        if not self._date_to:
            self._date_to = timezone.now()
            self.date_to = self.date_to

        if self.interval is None:
            self.interval = "day"

        self.period = data.get(PERIOD, self.period)
        total_seconds = (self.date_to - self.date_from).total_seconds()
        if self.period == "minute":
            self.num_intervals = int(divmod(total_seconds, 60)[0])
        elif self.period == "hour":
            self.num_intervals = int(divmod(total_seconds, 3600)[0])
        elif self.period == "day":
            self.num_intervals = int(divmod(total_seconds, 86400)[0])
        elif self.period == "week":
            self.num_intervals = (self.date_to - self.date_from).days // 7
        elif self.period == "month":
            self.num_intervals = (self.date_to.year - self.date_from.year) + (self.date_to.month - self.date_from.month)
        else:
            raise ValueError("{self.interval} not supported")
        self.num_intervals += 2

    def trunc_func(self, field_name: str) -> Union[TruncMinute, TruncHour, TruncDay, TruncWeek, TruncMonth]:
        if self.period == "minute":
            return TruncMinute(field_name)
        elif self.period == "hour":
            return TruncHour(field_name)
        elif self.period == "day":
            return TruncDay(field_name)
        elif self.period == "week":
            return TruncWeek(field_name)
        elif self.period == "month":
            return TruncMonth(field_name)
        else:
            raise ValueError("{self.interval} not supported")
