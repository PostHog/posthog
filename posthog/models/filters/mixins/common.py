import datetime
import json
import re
from typing import Any, Dict, List, Literal, Optional, Union, get_args

from dateutil.relativedelta import relativedelta
from django.db.models.query_utils import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from posthog.constants import (
    ACTIONS,
    BREAKDOWN,
    BREAKDOWN_GROUP_TYPE_INDEX,
    BREAKDOWN_LIMIT,
    BREAKDOWN_TYPE,
    BREAKDOWN_VALUE,
    BREAKDOWNS,
    COMPARE,
    DATE_FROM,
    DATE_TO,
    DEPRECATED_DISPLAY_TYPES,
    DISPLAY,
    DISPLAY_TYPES,
    EVENTS,
    EXCLUSIONS,
    FILTER_TEST_ACCOUNTS,
    FORMULA,
    INSIGHT,
    INSIGHT_TO_DISPLAY,
    INSIGHT_TRENDS,
    LIMIT,
    OFFSET,
    SELECTOR,
    SESSION,
    SHOWN_AS,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.models.entity import MATH_TYPE, Entity, ExclusionEntity
from posthog.models.filters.mixins.base import BaseParamMixin, BreakdownType
from posthog.models.filters.mixins.utils import cached_property, include_dict, process_bool
from posthog.models.filters.utils import GroupTypeIndex, validate_group_type_index
from posthog.utils import relative_date_parse

ALLOWED_FORMULA_CHARACTERS = r"([a-zA-Z \-\*\^0-9\+\/\(\)]+)"


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


class FilterTestAccountsMixin(BaseParamMixin):
    @cached_property
    def filter_test_accounts(self) -> bool:
        setting = self._data.get(FILTER_TEST_ACCOUNTS, None)
        if setting == True or setting == "true":
            return True
        return False

    @include_dict
    def filter_out_team_members_to_dict(self):
        return {"filter_test_accounts": self.filter_test_accounts} if self.filter_test_accounts else {}


class FormulaMixin(BaseParamMixin):
    @cached_property
    def formula(self) -> Optional[str]:
        formula = self._data.get(FORMULA, None)
        if not formula:
            return None
        return "".join(re.findall(ALLOWED_FORMULA_CHARACTERS, formula))

    @include_dict
    def formula_to_dict(self):
        return {"formula": self.formula} if self.formula else {}


class BreakdownMixin(BaseParamMixin):
    @cached_property
    def breakdown(self) -> Optional[Union[str, List[Union[str, int]]]]:
        breakdown = self._data.get(BREAKDOWN)

        if not isinstance(breakdown, str):
            return breakdown

        try:
            return json.loads(breakdown)
        except (TypeError, json.decoder.JSONDecodeError):
            return breakdown

    @cached_property
    def breakdowns(self) -> Optional[List[Dict[str, Any]]]:
        breakdowns = self._data.get(BREAKDOWNS)

        try:
            if isinstance(breakdowns, List):
                return breakdowns
            elif isinstance(breakdowns, str):
                return json.loads(breakdowns)
            else:
                return breakdowns

        except (TypeError, json.decoder.JSONDecodeError):
            raise ValidationError(detail="breakdowns must be a list of items, each with property and type")

    @cached_property
    def _breakdown_limit(self) -> Optional[int]:
        return self._data.get(BREAKDOWN_LIMIT)

    @property
    def breakdown_limit_or_default(self) -> int:
        return self._breakdown_limit or 10

    @include_dict
    def breakdown_to_dict(self):
        result: Dict = {}
        if self.breakdown:
            result[BREAKDOWN] = self.breakdown
        if self.breakdowns:
            result[BREAKDOWNS] = self.breakdowns
        if self._breakdown_limit:
            result[BREAKDOWN_LIMIT] = self._breakdown_limit

        return result

    @cached_property
    def breakdown_type(self) -> Optional[BreakdownType]:
        return self._data.get(BREAKDOWN_TYPE, None)

    @cached_property
    def breakdown_group_type_index(self) -> Optional[GroupTypeIndex]:
        value = self._data.get(BREAKDOWN_GROUP_TYPE_INDEX, None)
        return validate_group_type_index(BREAKDOWN_GROUP_TYPE_INDEX, value)

    @include_dict
    def breakdown_type_and_group_to_dict(self):
        if self.breakdown_type == "group":
            return {BREAKDOWN_TYPE: self.breakdown_type, BREAKDOWN_GROUP_TYPE_INDEX: self.breakdown_group_type_index}
        elif self.breakdown_type:
            return {BREAKDOWN_TYPE: self.breakdown_type}
        else:
            return {}


class BreakdownValueMixin(BaseParamMixin):
    @cached_property
    def breakdown_value(self) -> Optional[str]:
        return self._data.get(BREAKDOWN_VALUE, None)

    @include_dict
    def breakdown_value_to_dict(self):
        return {"breakdown_value": self.breakdown_value} if self.breakdown_value else {}


class InsightMixin(BaseParamMixin):
    @cached_property
    def insight(self) -> Literal["TRENDS", "FUNNELS", "RETENTION", "PATHS", "LIFECYCLE", "STICKINESS"]:
        return self._data.get(INSIGHT, INSIGHT_TRENDS).upper()

    @include_dict
    def insight_to_dict(self):
        return {"insight": self.insight}


class DisplayDerivedMixin(InsightMixin):
    @cached_property
    def display(self,) -> Literal[DISPLAY_TYPES]:
        return self._data.get(DISPLAY, INSIGHT_TO_DISPLAY[self.insight])

    @include_dict
    def display_to_dict(self):
        return {"display": self.display}


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
        offset_raw = self._data.get(OFFSET)
        return int(offset_raw) if offset_raw else 0

    @include_dict
    def offset_to_dict(self):
        return {"offset": self.offset} if self.offset else {}


class LimitMixin(BaseParamMixin):
    @cached_property
    def limit(self) -> int:
        limit_raw = self._data.get(LIMIT, None)
        return int(limit_raw) if limit_raw else 0

    @include_dict
    def limit_to_dict(self):
        return {"limit": self.limit} if self.limit else {}


class CompareMixin(BaseParamMixin):
    @cached_property
    def compare(self) -> bool:
        _compare = self._data.get(COMPARE, None)
        return process_bool(_compare)

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
        filter = Q(**{f"{field}__gte": date_from})
        if self.date_to:
            filter &= Q(**{f"{field}__lte": self.date_to})
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
        processed_entities: List[Entity] = []
        if self._data.get(ACTIONS):
            actions = self._data.get(ACTIONS, [])
            if isinstance(actions, str):
                actions = json.loads(actions)

            processed_entities.extend([Entity({**entity, "type": TREND_FILTER_TYPE_ACTIONS}) for entity in actions])
        if self._data.get(EVENTS):
            events = self._data.get(EVENTS, [])
            if isinstance(events, str):
                events = json.loads(events)
            processed_entities.extend([Entity({**entity, "type": TREND_FILTER_TYPE_EVENTS}) for entity in events])
        processed_entities.sort(key=lambda entity: entity.order if entity.order else -1)
        # Set sequential index values on entities
        for index, entity in enumerate(processed_entities):
            entity.index = index
        return processed_entities

    @cached_property
    def actions(self) -> List[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_ACTIONS]

    @cached_property
    def events(self) -> List[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_EVENTS]

    @cached_property
    def exclusions(self) -> List[ExclusionEntity]:
        _exclusions: List[ExclusionEntity] = []
        if self._data.get(EXCLUSIONS):
            exclusion_list = self._data.get(EXCLUSIONS, [])
            if isinstance(exclusion_list, str):
                exclusion_list = json.loads(exclusion_list)
            _exclusions.extend([ExclusionEntity({**entity}) for entity in exclusion_list])
        return _exclusions

    @include_dict
    def entities_to_dict(self):
        return {
            **({"events": [entity.to_dict() for entity in self.events]} if len(self.events) > 0 else {}),
            **({"actions": [entity.to_dict() for entity in self.actions]} if len(self.actions) > 0 else {}),
            **({"exclusions": [entity.to_dict() for entity in self.exclusions]} if len(self.exclusions) > 0 else {}),
        }


# These arguments are used to specify the target entity for insight actor retrieval on trend graphs
class EntityIdMixin(BaseParamMixin):
    @cached_property
    def target_entity_id(self) -> Optional[str]:
        return self._data.get("entityId", None) or self._data.get("entity_id", None)

    @include_dict
    def entity_id_to_dict(self):
        return {"entity_id": self.target_entity_id} if self.target_entity_id else {}


class EntityTypeMixin(BaseParamMixin):
    @cached_property
    def target_entity_type(self) -> Optional[str]:
        return self._data.get("type", None) or self._data.get("entity_type", None)

    @include_dict
    def entity_type_to_dict(self):
        return {"entity_type": self.target_entity_type} if self.target_entity_type else {}


class EntityMathMixin(BaseParamMixin):
    @cached_property
    def target_entity_math(self) -> Optional[MATH_TYPE]:
        return self._data.get("entity_math", None)

    @include_dict
    def entity_math_to_dict(self):
        return {"entity_math": self.target_entity_math} if self.target_entity_math else {}


class IncludeRecordingsMixin(BaseParamMixin):
    @cached_property
    def include_recordings(self) -> bool:
        return self._data.get("include_recordings") == "true"
