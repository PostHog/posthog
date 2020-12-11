import datetime
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.db.models.query_utils import Q
from django.http import HttpRequest
from django.utils import timezone

from posthog.constants import (
    DATE_FROM,
    DATE_TO,
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
from posthog.models.filters.filter import Filter
from posthog.utils import relative_date_parse

RETENTION_DEFAULT_INTERVALS = 11


class RetentionFilter(Filter):
    period: str = "Day"
    target_entity: Entity = Entity({"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS})
    retention_type: str = RETENTION_RECURRING
    total_intervals: int = RETENTION_DEFAULT_INTERVALS
    period_increment: Union[timedelta, relativedelta] = timedelta(days=1)
    total_increment: Union[timedelta, relativedelta] = timedelta(days=total_intervals)
    selected_interval: int = 0

    def __init__(self, data: Dict[str, Any] = {}, request: Optional[HttpRequest] = None, **kwargs) -> None:
        data["insight"] = INSIGHT_RETENTION
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
        tdelta, t1 = RetentionFilter.determine_time_delta(self.total_intervals, self.period)

        self.period_increment = t1
        self.total_increment = tdelta

    @property
    def date_from(self):
        _date_from = super().date_from
        date_to = self.date_to
        if not _date_from:
            _date_from = relative_date_parse("-11d")
        _date_from = date_to - self.total_increment

        if self.period == "Week":
            _date_from = _date_from - timedelta(days=_date_from.isoweekday() % 7)  # type: ignore

        return _date_from

    @property
    def people_date_filter_to_Q(self):
        date_from = self.date_from + self.selected_interval * self.period_increment
        date_to = date_from + self.period_increment
        if self._date_from == "all":
            return Q()
        if not date_from:
            date_from = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(days=7)
        filter = Q(timestamp__gte=date_from)
        if date_to:
            filter &= Q(timestamp__lte=date_to)
        return filter

    def people_reference_date_filter_to_Q(self, field: str = "timestamp"):
        date_from = self.date_from
        date_to = self.date_from + self.period_increment
        if self._date_from == "all":
            return Q()
        if not date_from:
            date_from = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(days=7)
        filter = Q(**{"{}__gte".format(field): date_from})
        if date_to:
            filter &= Q(**{"{}__lte".format(field): date_to})
        return filter

    @property
    def date_to(self):
        date_to = super().date_to + self.period_increment

        if self.period == "Hour":
            return date_to
        else:
            return date_to.replace(hour=0, minute=0, second=0, microsecond=0)

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

    def to_dict(self) -> Dict[str, Any]:
        common_vals = super().to_dict()

        date_to = super().date_to
        _date_to: Optional[str] = None
        if date_to:
            if self.period == "Hour":
                date_to = date_to
            else:
                date_to = date_to.replace(hour=0, minute=0, second=0, microsecond=0)
            _date_to = date_to.isoformat()

        date_from = super().date_from
        _date_from: Optional[str] = None
        if date_from:
            if self.period == "Hour":
                date_from = date_from
            else:
                date_from = date_from.replace(hour=0, minute=0, second=0, microsecond=0)
            _date_from = date_from.isoformat()

        full_dict = {
            **common_vals,
            DATE_FROM: _date_from,
            DATE_TO: _date_to,
            RETENTION_TYPE: self.retention_type,
            TOTAL_INTERVALS: self.total_intervals,
            SELECTED_INTERVAL: self.selected_interval,
            PERIOD: self.period,
            TARGET_ENTITY: self.target_entity.to_dict(),
        }
        return full_dict
