import json
import datetime
from functools import cached_property
from math import ceil
from typing import Any, Literal, Optional, Union
from zoneinfo import ZoneInfo

from django.utils import timezone

from dateutil.relativedelta import relativedelta
from rest_framework.exceptions import ValidationError

from posthog.hogql.constants import BREAKDOWN_VALUES_LIMIT, BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES

from posthog.constants import (
    ACTIONS,
    BREAKDOWN,
    BREAKDOWN_ATTRIBUTION_TYPE,
    BREAKDOWN_ATTRIBUTION_VALUE,
    BREAKDOWN_GROUP_TYPE_INDEX,
    BREAKDOWN_HIDE_OTHER_AGGREGATION,
    BREAKDOWN_HISTOGRAM_BIN_COUNT,
    BREAKDOWN_LIMIT,
    BREAKDOWN_NORMALIZE_URL,
    BREAKDOWN_TYPE,
    BREAKDOWNS,
    DATA_WAREHOUSE_ENTITIES,
    DATE_FROM,
    DATE_TO,
    DISPLAY,
    DISPLAY_TYPES,
    EVENTS,
    EXPLICIT_DATE,
    INSIGHT,
    INSIGHT_TO_DISPLAY,
    INSIGHT_TRENDS,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_DATA_WAREHOUSE,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_WORLD_MAP,
    BreakdownAttributionType,
)
from posthog.models.entity import Entity
from posthog.models.filters.mixins.base import BaseParamMixin, BreakdownType
from posthog.models.filters.mixins.utils import include_dict, include_query_tags, process_bool
from posthog.models.filters.utils import GroupTypeIndex, validate_group_type_index
from posthog.utils import DEFAULT_DATE_FROM_DAYS, relative_date_parse_with_delta_mapping


class BreakdownMixin(BaseParamMixin):
    @cached_property
    def breakdown(self) -> Optional[Union[str, list[Union[str, int]]]]:
        breakdown = self._data.get(BREAKDOWN)

        if not isinstance(breakdown, str):
            return breakdown

        try:
            return json.loads(breakdown)
        except (TypeError, json.decoder.JSONDecodeError):
            return breakdown

    @cached_property
    def breakdown_attribution_type(self) -> Optional[BreakdownAttributionType]:
        attribution_type = self._data.get(BREAKDOWN_ATTRIBUTION_TYPE)
        if not attribution_type:
            return BreakdownAttributionType.FIRST_TOUCH

        return attribution_type

    @cached_property
    def breakdown_attribution_value(self) -> Optional[int]:
        attribution_value = self._data.get(BREAKDOWN_ATTRIBUTION_VALUE)

        if attribution_value is None and self.breakdown_attribution_type == BreakdownAttributionType.STEP:
            raise ValueError(f'Missing required parameter "{BREAKDOWN_ATTRIBUTION_VALUE}" for attribution type "step"')

        return int(attribution_value) if attribution_value is not None else None

    @cached_property
    def breakdowns(self) -> Optional[list[dict[str, Any]]]:
        breakdowns = self._data.get(BREAKDOWNS)

        try:
            if isinstance(breakdowns, list):
                return breakdowns
            elif isinstance(breakdowns, str):
                return json.loads(breakdowns)
            else:
                return breakdowns

        except (TypeError, json.decoder.JSONDecodeError):
            raise ValidationError(detail="breakdowns must be a list of items, each with property and type")

    @cached_property
    def _breakdown_limit(self) -> Optional[int]:
        if BREAKDOWN_LIMIT in self._data:
            try:
                return int(self._data[BREAKDOWN_LIMIT])
            except (ValueError, TypeError):
                pass
        return None

    @property
    def breakdown_limit_or_default(self) -> int:
        return self._breakdown_limit or (
            BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES
            if getattr(self, "display", None) == TRENDS_WORLD_MAP
            else BREAKDOWN_VALUES_LIMIT
        )

    @cached_property
    def using_histogram(self) -> bool:
        return self.breakdown_histogram_bin_count is not None

    @cached_property
    def breakdown_histogram_bin_count(self) -> Optional[int]:
        if BREAKDOWN_HISTOGRAM_BIN_COUNT in self._data:
            try:
                return int(self._data[BREAKDOWN_HISTOGRAM_BIN_COUNT])
            except (ValueError, TypeError):
                pass
        return None

    @cached_property
    def breakdown_hide_other_aggregation(self) -> Optional[bool]:
        if BREAKDOWN_HIDE_OTHER_AGGREGATION in self._data:
            try:
                return self._data[BREAKDOWN_HIDE_OTHER_AGGREGATION] in ("True", "true", True)
            except (ValueError, TypeError):
                pass
        return None

    @include_dict
    def breakdown_to_dict(self):
        result: dict = {}
        if self.breakdown:
            result[BREAKDOWN] = self.breakdown
        if self.breakdowns:
            result[BREAKDOWNS] = self.breakdowns
        if self._breakdown_limit:
            result[BREAKDOWN_LIMIT] = self._breakdown_limit
        if self.breakdown_attribution_type:
            result[BREAKDOWN_ATTRIBUTION_TYPE] = self.breakdown_attribution_type
        if self.breakdown_attribution_value is not None:
            result[BREAKDOWN_ATTRIBUTION_VALUE] = self.breakdown_attribution_value
        if self.breakdown_histogram_bin_count is not None:
            result[BREAKDOWN_HISTOGRAM_BIN_COUNT] = self.breakdown_histogram_bin_count
        if self.breakdown_hide_other_aggregation is not None:
            result[BREAKDOWN_HIDE_OTHER_AGGREGATION] = self.breakdown_hide_other_aggregation
        if self.breakdown_normalize_url is not None:
            result[BREAKDOWN_NORMALIZE_URL] = self.breakdown_normalize_url
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
            return {
                BREAKDOWN_TYPE: self.breakdown_type,
                BREAKDOWN_GROUP_TYPE_INDEX: self.breakdown_group_type_index,
            }
        elif self.breakdown_type:
            return {BREAKDOWN_TYPE: self.breakdown_type}
        else:
            return {}

    @cached_property
    def breakdown_normalize_url(self) -> bool:
        """
        When breaking down by $current_url or $pathname, we ignore trailing slashes, question marks, and hashes.
        """
        bool_to_test = self._data.get("breakdown_normalize_url", False)
        return process_bool(bool_to_test)

    @include_query_tags
    def breakdown_query_tags(self):
        if self.breakdown_type:
            return {"breakdown_by": [self.breakdown_type]}

        return {}


class InsightMixin(BaseParamMixin):
    @cached_property
    def insight(self) -> Literal["TRENDS", "FUNNELS", "RETENTION", "PATHS", "LIFECYCLE", "STICKINESS"]:
        return self._data.get(INSIGHT, INSIGHT_TRENDS).upper()

    @include_dict
    def insight_to_dict(self):
        return {"insight": self.insight}


class DisplayDerivedMixin(InsightMixin):
    @cached_property
    def display(self) -> Literal[DISPLAY_TYPES]:
        return self._data.get(DISPLAY, INSIGHT_TO_DISPLAY[self.insight])

    @include_dict
    def display_to_dict(self):
        return {"display": self.display}


class DateMixin(BaseParamMixin):
    date_from_delta_mapping: Optional[dict[str, int]]
    date_to_delta_mapping: Optional[dict[str, int]]

    @cached_property
    def _date_from(self) -> Optional[Union[str, datetime.datetime]]:
        return self._data.get(DATE_FROM, None)

    @cached_property
    def _date_to(self) -> Optional[Union[str, datetime.datetime]]:
        return self._data.get(DATE_TO, None)

    @cached_property
    def date_from(self) -> Optional[datetime.datetime]:
        self.date_from_delta_mapping = None
        if self._date_from:
            if self._date_from == "all":
                return None
            elif isinstance(self._date_from, str):
                date, delta_mapping, _position = relative_date_parse_with_delta_mapping(
                    self._date_from,
                    self.team.timezone_info,  # type: ignore
                    always_truncate=True,
                )
                self.date_from_delta_mapping = delta_mapping
                return date
            else:
                return self._date_from
        return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(
            days=DEFAULT_DATE_FROM_DAYS
        )

    @cached_property
    def date_to(self) -> datetime.datetime:
        self.date_to_delta_mapping = None
        if not self._date_to:
            return timezone.now()
        else:
            if isinstance(self._date_to, str):
                try:
                    return datetime.datetime.strptime(self._date_to, "%Y-%m-%d").replace(
                        hour=23,
                        minute=59,
                        second=59,
                        microsecond=999999,
                        tzinfo=ZoneInfo("UTC"),
                    )
                except ValueError:
                    try:
                        return datetime.datetime.strptime(self._date_to, "%Y-%m-%d %H:%M:%S").replace(
                            tzinfo=ZoneInfo("UTC")
                        )
                    except ValueError:
                        (
                            date,
                            delta_mapping,
                            _position,
                        ) = relative_date_parse_with_delta_mapping(
                            self._date_to,
                            self.team.timezone_info,  # type: ignore
                            always_truncate=True,
                        )
                        self.date_to_delta_mapping = delta_mapping
                        return date
            else:
                return self._date_to

    @cached_property
    def use_explicit_dates(self) -> bool:
        return process_bool(self._data.get(EXPLICIT_DATE))

    @include_dict
    def date_to_dict(self) -> dict:
        result_dict = {}
        if self._date_from:
            result_dict.update(
                {
                    "date_from": self._date_from.isoformat()
                    if isinstance(self._date_from, datetime.datetime)
                    else self._date_from
                }
            )
        else:
            result_dict.update({"date_from": f"-{DEFAULT_DATE_FROM_DAYS}d"})

        if self._date_to:
            result_dict.update(
                {
                    "date_to": self._date_to.isoformat()
                    if isinstance(self._date_to, datetime.datetime)
                    else self._date_to
                }
            )

        if self.use_explicit_dates:
            result_dict.update({EXPLICIT_DATE: "true"})

        return result_dict

    @include_query_tags
    def query_tags_dates(self):
        if self.date_from and self.date_to:
            delta = self.date_to - self.date_from
            delta_days = ceil(delta.total_seconds() / datetime.timedelta(days=1).total_seconds())
            return {"query_time_range_days": delta_days}
        return {}


class EntitiesMixin(BaseParamMixin):
    @cached_property
    def entities(self) -> list[Entity]:
        processed_entities: list[Entity] = []
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
        if self._data.get(DATA_WAREHOUSE_ENTITIES):
            data_warehouse_entities = self._data.get(DATA_WAREHOUSE_ENTITIES, [])
            if isinstance(data_warehouse_entities, str):
                data_warehouse_entities = json.loads(data_warehouse_entities)
            processed_entities.extend(
                [Entity({**entity, "type": TREND_FILTER_TYPE_DATA_WAREHOUSE}) for entity in data_warehouse_entities]
            )

        processed_entities.sort(key=lambda entity: entity.order if entity.order else -1)
        # Set sequential index values on entities
        for index, entity in enumerate(processed_entities):
            entity.index = index
        return processed_entities

    @include_query_tags
    def query_tags_entities(self):
        return {"number_of_entities": len(self.entities)}

    @cached_property
    def actions(self) -> list[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_ACTIONS]

    @cached_property
    def events(self) -> list[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_EVENTS]

    @cached_property
    def data_warehouse_entities(self) -> list[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_DATA_WAREHOUSE]

    @include_dict
    def entities_to_dict(self):
        return {
            **({"events": [entity.to_dict() for entity in self.events]} if len(self.events) > 0 else {}),
            **({"actions": [entity.to_dict() for entity in self.actions]} if len(self.actions) > 0 else {}),
        }

    @include_query_tags
    def entities_query_tags(self):
        return {"entity_math": list({entity.math for entity in self.entities if entity.math})}
