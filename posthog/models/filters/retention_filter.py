import datetime
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.http import HttpRequest

from posthog.constants import (
    PERIOD,
    RETENTION_RECURRING,
    RETENTION_TYPE,
    SELECTED_INTERVAL,
    TARGET_ENTITY,
    TOTAL_INTERVALS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter

RETENTION_DEFAULT_INTERVALS = 11


class RetentionFilter(Filter):
    period: str = "Day"
    target_entity: Entity = Entity({"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS})
    retention_type: str = RETENTION_RECURRING
    total_intervals: int = RETENTION_DEFAULT_INTERVALS
    period_increment: Union[timedelta, relativedelta] = timedelta(days=1)
    total_increment: Union[timedelta, relativedelta] = timedelta(days=total_intervals)
    selected_interval: int = 0
    date_from: datetime.datetime

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        super().__init__(data, request)
        if request:
            data = {
                **request.GET.dict(),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")
        self.period = data.get(PERIOD, self.period)
        self.target_entity = self._parse_target_entity(data.get(TARGET_ENTITY)) or self.target_entity
        self.retention_type = data.get(RETENTION_TYPE, self.retention_type)
        self.total_intervals = data.get(TOTAL_INTERVALS, self.total_intervals)
        self.selected_interval = int(data.get(SELECTED_INTERVAL, 0))

        if not self.date_from:
            self._date_from = "-11d"

        tdelta, t1 = RetentionFilter.determine_time_delta(self.total_intervals, self.period)
        self._date_to = (self.date_to + t1).isoformat()

        if self.period == "Hour":
            date_to = self.date_to
            date_from: datetime.datetime = date_to - tdelta
        elif self.period == "Week":
            date_to = self.date_to.replace(hour=0, minute=0, second=0, microsecond=0)
            date_from = date_to - tdelta
            date_from = date_from - timedelta(days=date_from.isoweekday() % 7)
        else:
            date_to = self.date_to.replace(hour=0, minute=0, second=0, microsecond=0)
            date_from = date_to - tdelta

        self._date_from = date_from.isoformat()
        self._date_to = date_to.isoformat()
        self.period_increment = t1

    @property
    def returning_entity(self) -> Entity:
        return self.target_entity if not len(self.entities) > 0 else self.entities[0]

    @staticmethod
    def determine_time_delta(
        total_intervals: int, period: str
    ) -> Tuple[Union[timedelta, relativedelta], Union[timedelta, relativedelta]]:
        if period == "Hour":
            return timedelta(hours=total_intervals), timedelta(hours=1)
        elif period == "Week":
            return timedelta(weeks=total_intervals), timedelta(weeks=1)
        elif period == "Month":
            return relativedelta(months=total_intervals), relativedelta(months=1)
        elif period == "Day":
            return timedelta(days=total_intervals), timedelta(days=1)
        else:
            raise ValueError(f"Period {period} is unsupported.")
