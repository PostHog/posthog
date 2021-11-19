import json
from datetime import datetime, timedelta
from typing import Literal, Optional, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.db.models.query_utils import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from posthog.constants import (
    DISTINCT_ID_FILTER,
    PERIOD,
    RETENTION_RECURRING,
    RETENTION_TYPE,
    RETURNING_ENTITY,
    SELECTED_INTERVAL,
    TARGET_ENTITY,
    TOTAL_INTERVALS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.models.entity import Entity
from posthog.models.filters.mixins.common import BaseParamMixin, DateMixin, EntitiesMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict
from posthog.utils import relative_date_parse


class RetentionTypeMixin(BaseParamMixin):
    @cached_property
    def retention_type(self) -> Literal["retention_recurring", "retention_first_time"]:
        return self._data.get(RETENTION_TYPE, RETENTION_RECURRING)

    @include_dict
    def retention_type_to_dict(self):
        return {"retention_type": self.retention_type}


RETENTION_DEFAULT_INTERVALS = 11


class TotalIntervalsMixin(BaseParamMixin):
    @cached_property
    def total_intervals(self) -> int:
        return int(self._data.get(TOTAL_INTERVALS, RETENTION_DEFAULT_INTERVALS))

    @include_dict
    def total_intervals_to_dict(self):
        return {"total_intervals": self.total_intervals} if self.total_intervals else {}


class SelectedIntervalMixin(BaseParamMixin):
    @cached_property
    def selected_interval(self) -> int:
        return int(self._data.get(SELECTED_INTERVAL, 0))

    @include_dict
    def selected_interval_to_dict(self):
        return {"selected_interval": self.selected_interval} if self.selected_interval else {}


class PeriodMixin(BaseParamMixin):
    @cached_property
    def period(self) -> str:
        return self._data.get(PERIOD, "Day")

    @include_dict
    def period_to_dict(self):
        return {"period": self.period} if self.period else {}


class RetentionDateDerivedMixin(PeriodMixin, TotalIntervalsMixin, DateMixin, SelectedIntervalMixin):
    @cached_property
    def date_from(self) -> datetime:
        tdelta, _ = RetentionDateDerivedMixin.determine_time_delta(self.total_intervals, self.period)
        if self.period == "Hour":
            return self.date_to - tdelta
        elif self.period == "Week":
            date_from = self.date_to - tdelta
            return date_from - timedelta(days=date_from.isoweekday() % 7)
        else:
            date_to = self.date_to.replace(hour=0, minute=0, second=0, microsecond=0)
            return date_to - tdelta

    @cached_property
    def date_to(self) -> datetime:
        if self._date_to:
            if isinstance(self._date_to, str):
                date_to = relative_date_parse(self._date_to)
            else:
                date_to = self._date_to
        else:
            date_to = timezone.now()

        date_to = date_to + self.period_increment
        if self.period == "Hour":
            return date_to
        else:
            return date_to.replace(hour=0, minute=0, second=0, microsecond=0)

    @cached_property
    def period_increment(self) -> Union[timedelta, relativedelta]:
        _, t1 = RetentionDateDerivedMixin.determine_time_delta(self.total_intervals, self.period)
        return t1

    def reference_date_filter_Q(self, field: str = "timestamp") -> Q:
        date_from = self.date_from
        date_to = self.date_from + self.period_increment
        date_from = self.date_from
        if self._date_from == "all":
            return Q()
        if not date_from:
            date_from = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(days=7)
        filter = Q(**{f"{field}__gte": date_from})
        if date_to:
            filter &= Q(**{f"{field}__lte": date_to})
        return filter

    def recurring_date_filter_Q(self, field: str = "timestamp") -> Q:
        date_from = self.date_from + self.selected_interval * self.period_increment
        date_to = date_from + self.period_increment
        if self._date_from == "all":
            return Q()
        if not date_from:
            date_from = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(days=7)
        filter = Q(**{f"{field}__gte": date_from})
        if date_to:
            filter &= Q(**{f"{field}__lte": date_to})
        return filter

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
            raise ValidationError(f"Period {period} is unsupported.")


class EntitiesDerivedMixin(EntitiesMixin):
    @cached_property
    def target_entity(self) -> Entity:
        return self._parse_entity(self._data.get(TARGET_ENTITY)) or Entity(
            {"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS}
        )

    @include_dict
    def target_entity_to_dict(self):
        return {"target_entity": self.target_entity.to_dict()} if self.target_entity else {}

    def _parse_entity(self, entity_data) -> Optional[Entity]:
        if entity_data:
            if isinstance(entity_data, str):
                _data = json.loads(entity_data)
            else:
                _data = entity_data
            return Entity({"id": _data["id"], "type": _data["type"]})
        return None

    @cached_property
    def returning_entity(self) -> Entity:
        if self._data.get(RETURNING_ENTITY):
            return self._parse_entity(self._data[RETURNING_ENTITY]) or self.target_entity
        return self.target_entity

    @include_dict
    def returning_entity_to_dict(self):
        return {"returning_entity": self.returning_entity.to_dict()} if self.returning_entity else {}
