import datetime
import json
from distutils.util import strtobool
from functools import cached_property
from typing import Any, Dict, List, Optional, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.db.models import Exists, OuterRef, Q
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
    INTERVAL,
    OFFSET,
    PROPERTIES,
    SELECTOR,
    SESSION,
    SHOWN_AS,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.models.entity import Entity
from posthog.models.person import Person
from posthog.models.property import Property
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


class PropertyMixin(BaseParamMixin):
    @cached_property
    def properties(self) -> List[Property]:
        return self._parse_properties(self._data.get(PROPERTIES))

    def properties_to_Q(self, team_id: int, is_person_query: bool = False) -> Q:
        """
        Converts a filter to Q, for use in Django ORM .filter()
        If you're filtering a Person QuerySet, use is_person_query to avoid doing an unnecessary nested loop
        """
        filters = Q()

        if len(self.properties) == 0:
            return filters

        if is_person_query:
            for property in self.properties:
                filters &= property.property_to_Q()
            return filters

        person_properties = [prop for prop in self.properties if prop.type == "person"]
        if len(person_properties) > 0:
            person_Q = Q()
            for property in person_properties:
                person_Q &= property.property_to_Q()
            filters &= Q(Exists(Person.objects.filter(person_Q, id=OuterRef("person_id"),).only("pk")))

        for property in [prop for prop in self.properties if prop.type == "event"]:
            filters &= property.property_to_Q()

        # importing from .event and .cohort below to avoid importing from partially initialized modules

        element_properties = [prop for prop in self.properties if prop.type == "element"]
        if len(element_properties) > 0:
            from posthog.models.event import Event

            filters &= Q(
                Exists(
                    Event.objects.filter(pk=OuterRef("id"))
                    .filter(
                        **Event.objects.filter_by_element(
                            {item.key: item.value for item in element_properties}, team_id=team_id,
                        )
                    )
                    .only("id")
                )
            )

        cohort_properties = [prop for prop in self.properties if prop.type == "cohort"]
        if len(cohort_properties) > 0:
            from posthog.models.cohort import CohortPeople

            for item in cohort_properties:
                if item.key == "id":
                    filters &= Q(
                        Exists(
                            CohortPeople.objects.filter(
                                cohort_id=int(item.value), person_id=OuterRef("person_id"),
                            ).only("id")
                        )
                    )
        return filters

    def _parse_properties(self, properties: Optional[Any]) -> List[Property]:
        if isinstance(properties, list):
            return [Property(**property) for property in properties]
        if not properties:
            return []

        # old style dict properties
        ret = []
        for key, value in properties.items():
            key_split = key.split("__")
            ret.append(
                Property(
                    key=key_split[0], value=value, operator=key_split[1] if len(key_split) > 1 else None, type="event",
                )
            )
        return ret
