import datetime
import json
from distutils.util import strtobool
from functools import cached_property
from typing import Any, Dict, List, Optional, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone

from posthog.constants import (
    ACTIONS,
    BREAKDOWN,
    BREAKDOWN_TYPE,
    BREAKDOWN_VALUE,
    COMPARE,
    DATE_FROM,
    DATE_TO,
    DISPLAY,
    ENTITIES,
    EVENTS,
    INSIGHT,
    INTERVAL,
    OFFSET,
    PATH_TYPE,
    PROPERTIES,
    SELECTOR,
    SESSION,
    SHOWN_AS,
    START_POINT,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.models.entity import Entity
from posthog.models.property import Property, PropertyMixin
from posthog.utils import relative_date_parse


class BaseParamMixin:
    _data: Dict


class DisplayMixin(BaseParamMixin):
    @cached_property
    def display(self) -> Optional[str]:
        return self._data.get(DISPLAY, None)


class IntervalMixin(BaseParamMixin):
    @cached_property
    def interval(self) -> Optional[str]:
        return self._data.get(INTERVAL, None)


class SelectorMixin(BaseParamMixin):
    @cached_property
    def selector(self) -> Optional[str]:
        return self._data.get(SELECTOR, None)


class ShownAsMixin(BaseParamMixin):
    @cached_property
    def shown_as(self) -> Optional[str]:
        return self._data.get(SHOWN_AS, None)


class BreakdownMixin(BaseParamMixin):
    def _process_breakdown_param(self, breakdown: Optional[str]) -> Optional[Union[str, List[Union[str, int]]]]:
        if not isinstance(breakdown, str):
            return breakdown
        try:
            return json.loads(breakdown)
        except (TypeError, json.decoder.JSONDecodeError):
            return breakdown

    @cached_property
    def breakdown(self) -> Optional[Union[str, List[Union[str, int]]]]:
        breakdown = self._data.get(BREAKDOWN)
        return self._process_breakdown_param(breakdown)


class BreakdownTypeMixin(BaseParamMixin):
    @cached_property
    def breakdown_type(self) -> Optional[str]:
        return self._data.get(BREAKDOWN_TYPE, None)


class BreakdownValueMixin(BaseParamMixin):
    @cached_property
    def breakdown_value(self) -> Optional[str]:
        return self._data.get(BREAKDOWN_VALUE, None)


class InsightMixin(BaseParamMixin):
    @cached_property
    def insight(self) -> Optional[str]:
        return self._data.get(INSIGHT, None)


class SessionTypeMixin(BaseParamMixin):
    @cached_property
    def session_type(self) -> Optional[str]:
        return self._data.get(SESSION, None)


class OffsetMixin(BaseParamMixin):
    @cached_property
    def offset(self) -> int:
        _offset = self._data.get(OFFSET)
        return int(_offset or "0")


class CompareMixin(BaseParamMixin):
    def _process_compare(self, compare: Optional[str]) -> bool:
        if isinstance(compare, bool):
            return compare
        elif isinstance(compare, str):
            return bool(strtobool(compare))
        else:
            return False

    @cached_property
    def compare(self) -> bool:
        _compare = self._data.get(COMPARE, None)
        return self._process_compare(_compare)


class DateMixin(BaseParamMixin):
    @cached_property
    def _date_from(self) -> Optional[Union[str, datetime.datetime]]:
        return self._data.get(DATE_FROM, None)

    @cached_property
    def _date_to(self) -> Optional[Union[str, datetime.datetime]]:
        return self._data.get(DATE_TO, None)

    @cached_property
    def date_from(self) -> Optional[datetime.datetime]:
        if self._date_from:
            if self._date_from == "all":
                return None
            elif isinstance(self._date_from, str):
                return relative_date_parse(self._date_from)
            else:
                return self._date_from
        return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(days=7)

    @cached_property
    def date_to(self) -> datetime.datetime:
        if self._date_to:
            if isinstance(self._date_to, str):
                return relative_date_parse(self._date_to)
            else:
                return self._date_to
        return timezone.now()


class EntitiesMixin(BaseParamMixin):
    @cached_property
    def entities(self) -> List[Entity]:
        _entities: List[Entity] = []
        if self._data.get(ACTIONS):
            _entities.extend(
                [Entity({**entity, "type": TREND_FILTER_TYPE_ACTIONS}) for entity in self._data.get(ACTIONS, [])]
            )
        if self._data.get(EVENTS):
            _entities.extend(
                [Entity({**entity, "type": TREND_FILTER_TYPE_EVENTS}) for entity in self._data.get(EVENTS, [])]
            )
        return sorted(_entities, key=lambda entity: entity.order if entity.order else -1)

    @cached_property
    def actions(self) -> List[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_ACTIONS]

    @cached_property
    def events(self) -> List[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_EVENTS]
