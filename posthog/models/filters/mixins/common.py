import datetime
import json
import re
from math import ceil
from typing import Any, Dict, List, Literal, Optional, Union, cast

from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from posthog.constants import (
    ACTIONS,
    BREAKDOWN,
    BREAKDOWN_ATTRIBUTION_TYPE,
    BREAKDOWN_ATTRIBUTION_VALUE,
    BREAKDOWN_GROUP_TYPE_INDEX,
    BREAKDOWN_HISTOGRAM_BIN_COUNT,
    BREAKDOWN_LIMIT,
    BREAKDOWN_NORMALIZE_URL,
    BREAKDOWN_TYPE,
    BREAKDOWN_VALUE,
    BREAKDOWN_VALUES_LIMIT,
    BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES,
    BREAKDOWNS,
    CLIENT_QUERY_ID,
    COMPARE,
    DATE_FROM,
    DATE_TO,
    DISPLAY,
    DISPLAY_TYPES,
    EVENTS,
    EXCLUSIONS,
    EXPLICIT_DATE,
    FILTER_TEST_ACCOUNTS,
    FORMULA,
    INSIGHT,
    INSIGHT_TO_DISPLAY,
    INSIGHT_TRENDS,
    LIMIT,
    OFFSET,
    SAMPLING_FACTOR,
    SELECTOR,
    SHOWN_AS,
    SMOOTHING_INTERVALS,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_WORLD_MAP,
    BreakdownAttributionType,
)
from posthog.models.entity import Entity, ExclusionEntity, MathType
from posthog.models.filters.mixins.base import BaseParamMixin, BreakdownType
from posthog.models.filters.mixins.utils import cached_property, include_dict, include_query_tags, process_bool
from posthog.models.filters.utils import GroupTypeIndex, validate_group_type_index
from posthog.utils import DEFAULT_DATE_FROM_DAYS, relative_date_parse_with_delta_mapping

# When updating this regex, remember to update the regex with the same name in TrendsFormula.tsx
ALLOWED_FORMULA_CHARACTERS = r"([a-zA-Z \-*^0-9+/().]+)"


class SmoothingIntervalsMixin(BaseParamMixin):
    @cached_property
    def smoothing_intervals(self) -> int:
        interval_candidate_string = self._data.get(SMOOTHING_INTERVALS)
        if not interval_candidate_string:
            return 1
        try:
            interval_candidate = int(interval_candidate_string)
            if interval_candidate < 1:
                raise ValueError(f"Smoothing intervals must be a positive integer!")
        except ValueError:
            raise ValueError(f"Smoothing intervals must be a positive integer!")
        return cast(int, interval_candidate)

    @include_dict
    def smoothing_intervals_to_dict(self):
        return {SMOOTHING_INTERVALS: self.smoothing_intervals}


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


class ClientQueryIdMixin(BaseParamMixin):
    @cached_property
    def client_query_id(self) -> Optional[str]:
        return self._data.get(CLIENT_QUERY_ID, None)

    @include_query_tags
    def client_query_tags(self):
        return {"client_query_id": self.client_query_id} if self.client_query_id else {}


class FilterTestAccountsMixin(BaseParamMixin):
    @cached_property
    def filter_test_accounts(self) -> bool:
        setting = self._data.get(FILTER_TEST_ACCOUNTS, None)
        if setting is True or setting == "true":
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
        if BREAKDOWN_LIMIT in self._data:
            try:
                return int(self._data[BREAKDOWN_LIMIT])
            except ValueError:
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
            except ValueError:
                pass
        return None

    @include_dict
    def breakdown_to_dict(self):
        result: Dict = {}
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
            return {BREAKDOWN_TYPE: self.breakdown_type, BREAKDOWN_GROUP_TYPE_INDEX: self.breakdown_group_type_index}
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
    def display(self) -> Literal[DISPLAY_TYPES]:
        return self._data.get(DISPLAY, INSIGHT_TO_DISPLAY[self.insight])

    @include_dict
    def display_to_dict(self):
        return {"display": self.display}


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
    date_from_delta_mapping: Optional[Dict[str, int]]
    date_to_delta_mapping: Optional[Dict[str, int]]

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
                date, delta_mapping = relative_date_parse_with_delta_mapping(self._date_from, self.team.timezone_info, always_truncate=True)  # type: ignore
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
                        hour=23, minute=59, second=59, microsecond=999999, tzinfo=ZoneInfo("UTC")
                    )
                except ValueError:
                    try:
                        return datetime.datetime.strptime(self._date_to, "%Y-%m-%d %H:%M:%S").replace(
                            tzinfo=ZoneInfo("UTC")
                        )
                    except ValueError:
                        date, delta_mapping = relative_date_parse_with_delta_mapping(self._date_to, self.team.timezone_info, always_truncate=True)  # type: ignore
                        self.date_to_delta_mapping = delta_mapping
                        return date
            else:
                return self._date_to

    @cached_property
    def use_explicit_dates(self) -> bool:
        return process_bool(self._data.get(EXPLICIT_DATE))

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

    @include_query_tags
    def query_tags_entities(self):
        return {"number_of_entities": len(self.entities)}

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

            _exclusions.extend([ExclusionEntity({**entity}) for entity in exclusion_list if entity])

        return _exclusions

    @include_dict
    def entities_to_dict(self):
        return {
            **({"events": [entity.to_dict() for entity in self.events]} if len(self.events) > 0 else {}),
            **({"actions": [entity.to_dict() for entity in self.actions]} if len(self.actions) > 0 else {}),
            **({"exclusions": [entity.to_dict() for entity in self.exclusions]} if len(self.exclusions) > 0 else {}),
        }

    @include_query_tags
    def entities_query_tags(self):
        return {"entity_math": list(set(entity.math for entity in self.entities if entity.math))}


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
    def target_entity_math(self) -> Optional[MathType]:
        return self._data.get("entity_math", None)

    @include_dict
    def entity_math_to_dict(self):
        return {"entity_math": self.target_entity_math} if self.target_entity_math else {}


class EntityOrderMixin(BaseParamMixin):
    @cached_property
    def target_entity_order(self) -> Optional[str]:
        return self._data.get("entity_order", None) or self._data.get("entity_order", None)

    @include_dict
    def entity_order_to_dict(self):
        return {"entity_order": self.target_entity_order} if self.target_entity_order else {}


class IncludeRecordingsMixin(BaseParamMixin):
    @cached_property
    def include_recordings(self) -> bool:
        include_recordings = self._data.get("include_recordings")
        return include_recordings is True or include_recordings == "true"

    @include_dict
    def include_recordings_to_dict(self):
        return {"include_recordings": self.include_recordings} if self.include_recordings else {}


class SearchMixin(BaseParamMixin):
    @cached_property
    def search(self) -> Optional[str]:
        search = self._data.get("search", None)
        return search

    @include_dict
    def search_to_dict(self):
        return {"search": self.search} if self.search else {}


class DistinctIdMixin(BaseParamMixin):
    """
    Filter on distinct id. Only used for person endpoint
    """

    @cached_property
    def distinct_id(self) -> Optional[str]:
        distinct_id = self._data.get("distinct_id", None)
        return distinct_id


class EmailMixin(BaseParamMixin):
    """
    Filter on email. Only used for person endpoint
    """

    @cached_property
    def email(self) -> Optional[str]:
        email = self._data.get("email", None)
        return email


class UpdatedAfterMixin(BaseParamMixin):
    """
    Filter on updated after (parsable by CH parseDateTimeBestEffort). Only used for person endpoint
    """

    @cached_property
    def updated_after(self) -> Optional[str]:
        updated_after = self._data.get("updated_after", None)
        return updated_after


class SampleMixin(BaseParamMixin):
    """
    Sample factor for a query.
    """

    @cached_property
    def sampling_factor(self) -> Optional[float]:
        sampling_factor = self._data.get("sampling_factor", None)

        # cover for both None and empty strings - also ok to filter out 0s here
        if sampling_factor:
            sampling_factor = float(sampling_factor)
            if sampling_factor < 0 or sampling_factor > 1:
                raise ValueError("Sampling factor must be greater than 0 and smaller or equal to 1")

            return sampling_factor

        return None

    @include_dict
    def sampling_factor_to_dict(self):
        return {SAMPLING_FACTOR: self.sampling_factor or ""}


class AggregationAxisMixin(BaseParamMixin):
    """
    Aggregation Axis. Only used frontend side.
    """

    @cached_property
    def aggregation_axis_format(self) -> Optional[str]:
        return self._data.get("aggregation_axis_format", None)

    @cached_property
    def aggregation_axis_prefix(self) -> Optional[str]:
        return self._data.get("aggregation_axis_prefix", None)

    @cached_property
    def aggregation_axis_postfix(self) -> Optional[str]:
        return self._data.get("aggregation_axis_postfix", None)
