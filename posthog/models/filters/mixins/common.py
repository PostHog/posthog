import datetime
import json
from distutils.util import strtobool
from typing import Dict, List, Optional, Union

from dateutil.relativedelta import relativedelta
from django.db.models.query_utils import Q
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
    EVENTS,
    INSIGHT,
    INSIGHT_TO_DISPLAY,
    INSIGHT_TRENDS,
    INTERVAL,
    OFFSET,
    SELECTOR,
    SESSION,
    SHOWN_AS,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.models.entity import Entity
from posthog.models.filters.mixins.base import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict
from posthog.utils import relative_date_parse


class IntervalMixin(BaseParamMixin):
    @cached_property
    def interval(self) -> str:
        return self._data.get(INTERVAL, "day")

    @include_dict
    def interval_to_dict(self):
        return {"interval": self.interval} if self.interval else {}


class SelectorMixin(BaseParamMixin):
    @cached_property
    def selector(self) -> Optional[str]:
        return self._data.get(SELECTOR, None)

    @include_dict
    def selector_to_dict(self):
        return {"selector": self.selector} if self.selector else {}


class ShownAsMixin(BaseParamMixin):
    @cached_property
    def shown_as(self) -> Optional[str]:
        return self._data.get(SHOWN_AS, None)

    @include_dict
    def shown_as_to_dict(self):
        return {"shown_as": self.shown_as} if self.shown_as else {}


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

    @include_dict
    def breakdown_to_dict(self):
        return {"breakdown": self.breakdown} if self.breakdown else {}


class BreakdownTypeMixin(BaseParamMixin):
    @cached_property
    def breakdown_type(self) -> Optional[str]:
        return self._data.get(BREAKDOWN_TYPE, None)

    @include_dict
    def breakdown_type_to_dict(self):
        return {"breakdown_type": self.breakdown_type} if self.breakdown_type else {}


class BreakdownValueMixin(BaseParamMixin):
    @cached_property
    def breakdown_value(self) -> Optional[str]:
        return self._data.get(BREAKDOWN_VALUE, None)

    @include_dict
    def breakdown_value_to_dict(self):
        return {"breakdown_value": self.breakdown_value} if self.breakdown_value else {}


class InsightMixin(BaseParamMixin):
    @cached_property
    def insight(self) -> str:
        return self._data.get(INSIGHT, INSIGHT_TRENDS)

    @include_dict
    def insight_to_dict(self):
        return {"insight": self.insight} if self.insight else {}


class DisplayDerivedMixin(InsightMixin):
    @cached_property
    def display(self) -> str:
        return self._data.get(DISPLAY, INSIGHT_TO_DISPLAY[self.insight])

    @include_dict
    def display_to_dict(self):
        return {"display": self.display} if self.display else {}


class SessionMixin(BaseParamMixin):
    @cached_property
    def session(self) -> Optional[str]:
        return self._data.get(SESSION, None)

    @include_dict
    def session_to_dict(self):
        return {"session": self.session} if self.session else {}


class OffsetMixin(BaseParamMixin):
    @cached_property
    def offset(self) -> int:
        _offset = self._data.get(OFFSET)
        return int(_offset or "0")


class CompareMixin(BaseParamMixin):
    def _process_compare(self, compare: Optional[Union[str, bool]]) -> bool:
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

    @include_dict
    def compare_to_dict(self):
        return {"compare": self.compare} if self.compare else {}


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

    @cached_property
    def date_filter_Q(self) -> Q:
        date_from = self.date_from
        if self._date_from == "all":
            return Q()
        if not date_from:
            date_from = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(days=7)
        filter = Q(timestamp__gte=date_from)
        if self.date_to:
            filter &= Q(timestamp__lte=self.date_to)
        return filter

    def custom_date_filter_Q(self, field: str = "timestamp") -> Q:
        date_from = self.date_from
        if self._date_from == "all":
            return Q()
        if not date_from:
            date_from = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(days=7)
        filter = Q(**{"{}__gte".format(field): date_from})
        if self.date_to:
            filter &= Q(**{"{}__lte".format(field): self.date_to})
        return filter

    @include_dict
    def date_to_dict(self) -> Dict:
        result_dict = {}
        if self._date_from:
            result_dict.update(
                {
                    "date_from": self._date_from.isoformat()
                    if isinstance(self._date_from, datetime.datetime)
                    else self._date_from
                }
            )

        if self._date_to:
            result_dict.update(
                {
                    "date_to": self._date_to.isoformat()
                    if isinstance(self._date_to, datetime.datetime)
                    else self._date_to
                }
            )

        return result_dict


class EntitiesMixin(BaseParamMixin):
    @cached_property
    def entities(self) -> List[Entity]:
        _entities: List[Entity] = []
        if self._data.get(ACTIONS):
            actions = self._data.get(ACTIONS, [])
            if isinstance(actions, str):
                actions = json.loads(actions)

            _entities.extend([Entity({**entity, "type": TREND_FILTER_TYPE_ACTIONS}) for entity in actions])
        if self._data.get(EVENTS):
            events = self._data.get(EVENTS, [])
            if isinstance(events, str):
                events = json.loads(events)
            _entities.extend([Entity({**entity, "type": TREND_FILTER_TYPE_EVENTS}) for entity in events])
        return sorted(_entities, key=lambda entity: entity.order if entity.order else -1)

    @cached_property
    def actions(self) -> List[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_ACTIONS]

    @cached_property
    def events(self) -> List[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_EVENTS]

    @include_dict
    def entities_to_dict(self):
        return {
            **({"events": [entity.to_dict() for entity in self.events]} if len(self.events) > 0 else {}),
            **({"actions": [entity.to_dict() for entity in self.actions]} if len(self.actions) > 0 else {}),
        }
