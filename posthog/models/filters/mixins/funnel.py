import datetime
import json
from typing import TYPE_CHECKING, Dict, List, Literal, Optional, Union

from posthog.models.property import Property

if TYPE_CHECKING:
    from posthog.models.entity import Entity

from rest_framework.exceptions import ValidationError

from posthog.constants import (
    BIN_COUNT,
    DISPLAY,
    DROP_OFF,
    ENTRANCE_PERIOD_START,
    FUNNEL_CORRELATION_EVENT_EXCLUDE_PROPERTY_NAMES,
    FUNNEL_CORRELATION_EVENT_NAMES,
    FUNNEL_CORRELATION_EXCLUDE_EVENT_NAMES,
    FUNNEL_CORRELATION_EXCLUDE_NAMES,
    FUNNEL_CORRELATION_NAMES,
    FUNNEL_CORRELATION_PERSON_CONVERTED,
    FUNNEL_CORRELATION_PERSON_ENTITY,
    FUNNEL_CORRELATION_PERSON_LIMIT,
    FUNNEL_CORRELATION_PERSON_OFFSET,
    FUNNEL_CORRELATION_PROPERTY_VALUES,
    FUNNEL_CORRELATION_TYPE,
    FUNNEL_CUSTOM_STEPS,
    FUNNEL_FROM_STEP,
    FUNNEL_LAYOUT,
    FUNNEL_ORDER_TYPE,
    FUNNEL_STEP,
    FUNNEL_STEP_BREAKDOWN,
    FUNNEL_TO_STEP,
    FUNNEL_VIZ_TYPE,
    FUNNEL_WINDOW_DAYS,
    FUNNEL_WINDOW_INTERVAL,
    FUNNEL_WINDOW_INTERVAL_UNIT,
    INSIGHT,
    INSIGHT_FUNNELS,
    TRENDS_LINEAR,
    FunnelCorrelationType,
    FunnelOrderType,
    FunnelVizType,
)
from posthog.models.filters.mixins.base import BaseParamMixin, IntervalType
from posthog.models.filters.mixins.utils import cached_property, include_dict
from posthog.utils import relative_date_parse, str_to_bool


class FunnelFromToStepsMixin(BaseParamMixin):
    @cached_property
    def funnel_from_step(self) -> Optional[int]:
        if self._data.get(FUNNEL_FROM_STEP) is not None:
            return int(self._data[FUNNEL_FROM_STEP])
        return None

    @cached_property
    def funnel_to_step(self) -> Optional[int]:
        if self._data.get(FUNNEL_TO_STEP) is not None:
            return int(self._data[FUNNEL_TO_STEP])
        return None

    @include_dict
    def funnel_from_to_steps_to_dict(self):
        dict_part = {}
        if self.funnel_from_step is not None:
            dict_part[FUNNEL_FROM_STEP] = self.funnel_from_step
        if self.funnel_to_step is not None:
            dict_part[FUNNEL_TO_STEP] = self.funnel_to_step
        return dict_part


class FunnelWindowDaysMixin(BaseParamMixin):
    @cached_property
    def funnel_window_days(self) -> Optional[int]:
        _days = int(self._data.get(FUNNEL_WINDOW_DAYS, "0"))
        if _days == 0:
            return None
        return _days

    @include_dict
    def funnel_window_days_to_dict(self):
        return {FUNNEL_WINDOW_DAYS: self.funnel_window_days} if self.funnel_window_days else {}

    @staticmethod
    def milliseconds_from_days(days):
        milliseconds, seconds, minutes, hours = [1000, 60, 60, 24]
        return milliseconds * seconds * minutes * hours * days

    @staticmethod
    def microseconds_from_days(days):
        microseconds = 1000
        return microseconds * FunnelWindowDaysMixin.milliseconds_from_days(days)


class FunnelWindowMixin(BaseParamMixin):
    @cached_property
    def funnel_window_interval(self) -> Optional[int]:
        _amt = int(self._data.get(FUNNEL_WINDOW_INTERVAL, "0"))
        if _amt == 0:
            return None
        return _amt

    @cached_property
    def funnel_window_interval_unit(self) -> Optional[IntervalType]:
        _unit = self._data.get(FUNNEL_WINDOW_INTERVAL_UNIT, None)
        return _unit.lower() if _unit is not None else _unit

    @include_dict
    def funnel_window_to_dict(self):
        dict_part: Dict = {}
        if self.funnel_window_interval is not None:
            dict_part[FUNNEL_WINDOW_INTERVAL] = self.funnel_window_interval
        if self.funnel_window_interval_unit is not None:
            dict_part[FUNNEL_WINDOW_INTERVAL_UNIT] = self.funnel_window_interval_unit
        return dict_part

    def funnel_window_interval_unit_ch(self) -> Literal["DAY", "MINUTE", "HOUR", "WEEK", "MONTH"]:
        if self.funnel_window_interval_unit is None:
            return "DAY"

        if self.funnel_window_interval_unit == "minute":
            return "MINUTE"
        elif self.funnel_window_interval_unit == "hour":
            return "HOUR"
        elif self.funnel_window_interval_unit == "week":
            return "WEEK"
        elif self.funnel_window_interval_unit == "month":
            return "MONTH"
        elif self.funnel_window_interval_unit == "day":
            return "DAY"
        else:
            raise ValidationError("{interval} not supported")


class FunnelPersonsStepMixin(BaseParamMixin):
    # first step is 0
    # -1 means dropoff into step 1
    @cached_property
    def funnel_step(self) -> Optional[int]:
        """
        Specifies the step index within a funnel entities definition for which
        we want to get the `timestamp` for, per person.
        """
        _step_as_string = self._data.get(FUNNEL_STEP)

        if _step_as_string is None:
            return None
        return int(_step_as_string)

    @cached_property
    def funnel_custom_steps(self) -> List[int]:
        """
        Custom step numbers to get persons for. This overrides FunnelPersonsStepMixin::funnel_step
        """
        raw_steps = self._data.get(FUNNEL_CUSTOM_STEPS, [])
        if isinstance(raw_steps, str):
            return json.loads(raw_steps)

        return raw_steps

    @include_dict
    def funnel_step_to_dict(self):
        result: dict = {}
        if self.funnel_step is not None:
            result[FUNNEL_STEP] = self.funnel_step
        if self.funnel_custom_steps:
            result[FUNNEL_CUSTOM_STEPS] = self.funnel_custom_steps
        return result


class FunnelPersonsStepBreakdownMixin(BaseParamMixin):
    @cached_property
    def funnel_step_breakdown(self) -> Optional[Union[List[str], int, str]]:
        """
        The breakdown value for which to get persons for.

        For person and event properties as this value is set within the funnel it is always an array.
        Until multi property breakdowns is released it is always a single value array

        for groups it is always a string

        for cohorts it is always an int
        """
        raw: Optional[str] = self._data.get(FUNNEL_STEP_BREAKDOWN)
        if not raw:
            return raw

        try:
            return json.loads(raw)
        except (TypeError, json.decoder.JSONDecodeError):
            return raw

    @include_dict
    def funnel_person_breakdown_to_dict(self):
        return {FUNNEL_STEP_BREAKDOWN: self.funnel_step_breakdown} if self.funnel_step_breakdown is not None else {}


class FunnelLayoutMixin(BaseParamMixin):
    @cached_property
    def layout(self) -> Optional[Literal["horizontal", "vertical"]]:
        return self._data.get(FUNNEL_LAYOUT)

    @include_dict
    def layout_to_dict(self):
        return {FUNNEL_LAYOUT: self.layout} if self.layout else {}


class FunnelTypeMixin(BaseParamMixin):
    @cached_property
    def funnel_order_type(self) -> Optional[FunnelOrderType]:
        return self._data.get(FUNNEL_ORDER_TYPE)

    @cached_property
    def funnel_viz_type(self) -> Optional[FunnelVizType]:
        funnel_viz_type = self._data.get(FUNNEL_VIZ_TYPE)
        if (
            funnel_viz_type is None
            and self._data.get(INSIGHT) == INSIGHT_FUNNELS
            and self._data.get(DISPLAY) == TRENDS_LINEAR
        ):
            # Backwards compatibility
            # Before Filter.funnel_viz_type funnel trends were indicated by Filter.display being TRENDS_LINEAR
            return FunnelVizType.TRENDS
        return funnel_viz_type

    @include_dict
    def funnel_type_to_dict(self):
        result: Dict[str, str] = {}
        if self.funnel_order_type:
            result[FUNNEL_ORDER_TYPE] = self.funnel_order_type
        if self.funnel_viz_type:
            result[FUNNEL_VIZ_TYPE] = self.funnel_viz_type
        return result


class HistogramMixin(BaseParamMixin):
    @cached_property
    def bin_count(self) -> Optional[int]:
        bin_count = self._data.get(BIN_COUNT)
        return int(bin_count) if bin_count else None

    @include_dict
    def histogram_to_dict(self):
        return {"bin_count": self.bin_count} if self.bin_count else {}


class FunnelTrendsPersonsMixin(BaseParamMixin):
    @cached_property
    def entrance_period_start(self) -> Optional[datetime.datetime]:
        entrance_period_start_raw = self._data.get(ENTRANCE_PERIOD_START)
        return relative_date_parse(entrance_period_start_raw) if entrance_period_start_raw else None

    @cached_property
    def drop_off(self) -> Optional[bool]:
        drop_off_raw = self._data.get(DROP_OFF)
        return str_to_bool(str(drop_off_raw)) if drop_off_raw is not None else None

    @include_dict
    def funnel_trends_persons_to_dict(self):
        result_dict: Dict = {}
        if self.entrance_period_start:
            result_dict[ENTRANCE_PERIOD_START] = self.entrance_period_start.isoformat()
        if self.drop_off is not None:
            result_dict[DROP_OFF] = self.drop_off
        return result_dict


class FunnelCorrelationMixin(BaseParamMixin):
    @cached_property
    def correlation_type(self) -> Optional[FunnelCorrelationType]:
        raw_type = self._data.get(FUNNEL_CORRELATION_TYPE)
        if raw_type:
            try:
                return FunnelCorrelationType(raw_type)
            except ValueError:
                return None

        return None

    @cached_property
    def correlation_property_names(self) -> List[str]:
        # Person Property names for which to run Person Properties correlation
        property_names = self._data.get(FUNNEL_CORRELATION_NAMES, [])
        if isinstance(property_names, str):
            return json.loads(property_names)
        return property_names

    @cached_property
    def correlation_property_exclude_names(self) -> List[str]:
        # Person Property names to exclude from Person Properties correlation
        property_names = self._data.get(FUNNEL_CORRELATION_EXCLUDE_NAMES, [])
        if isinstance(property_names, str):
            return json.loads(property_names)
        return property_names

    @cached_property
    def correlation_event_names(self) -> List[str]:
        # Event names for which to run EventWithProperties correlation
        event_names = self._data.get(FUNNEL_CORRELATION_EVENT_NAMES, [])
        if isinstance(event_names, str):
            return json.loads(event_names)
        return event_names

    @cached_property
    def correlation_event_exclude_names(self) -> List[str]:
        # Exclude event names from Event correlation
        property_names = self._data.get(FUNNEL_CORRELATION_EXCLUDE_EVENT_NAMES, [])
        if isinstance(property_names, str):
            return json.loads(property_names)
        return property_names

    @cached_property
    def correlation_event_exclude_property_names(self) -> List[str]:
        # Event Property names to exclude from EventWithProperties correlation
        property_names = self._data.get(FUNNEL_CORRELATION_EVENT_EXCLUDE_PROPERTY_NAMES, [])
        if isinstance(property_names, str):
            return json.loads(property_names)
        return property_names

    @include_dict
    def funnel_correlation_to_dict(self):
        result_dict: Dict = {}
        if self.correlation_type:
            result_dict[FUNNEL_CORRELATION_TYPE] = self.correlation_type
        if self.correlation_property_names:
            result_dict[FUNNEL_CORRELATION_NAMES] = self.correlation_property_names
        if self.correlation_property_exclude_names:
            result_dict[FUNNEL_CORRELATION_EXCLUDE_NAMES] = self.correlation_property_exclude_names
        if self.correlation_event_names:
            result_dict[FUNNEL_CORRELATION_EVENT_NAMES] = self.correlation_event_names
        if self.correlation_event_exclude_names:
            result_dict[FUNNEL_CORRELATION_EXCLUDE_EVENT_NAMES] = self.correlation_event_exclude_names
        if self.correlation_event_exclude_property_names:
            result_dict[FUNNEL_CORRELATION_EVENT_EXCLUDE_PROPERTY_NAMES] = self.correlation_event_exclude_property_names
        return result_dict


class FunnelCorrelationActorsMixin(BaseParamMixin):
    @cached_property
    def correlation_person_entity(self) -> Optional["Entity"]:
        # Used for event & event_with_properties correlations persons
        from posthog.models.entity import Entity

        raw_event = self._data.get(FUNNEL_CORRELATION_PERSON_ENTITY)
        if isinstance(raw_event, str):
            event = json.loads(raw_event)
        else:
            event = raw_event

        return Entity(event) if event else None

    @cached_property
    def correlation_property_values(self) -> Optional[List[Property]]:
        # Used for property correlations persons

        _props = self._data.get(FUNNEL_CORRELATION_PROPERTY_VALUES)

        if not _props:
            return None

        if isinstance(_props, str):
            try:
                loaded_props = json.loads(_props)
            except json.decoder.JSONDecodeError:
                raise ValidationError("Properties are unparsable!")
        else:
            loaded_props = _props

        if isinstance(loaded_props, list):
            _properties = []
            for prop_params in loaded_props:
                if isinstance(prop_params, Property):
                    _properties.append(prop_params)
                else:
                    try:
                        new_prop = Property(**prop_params)
                        _properties.append(new_prop)
                    except:
                        continue
            return _properties
        return None

    @cached_property
    def correlation_person_limit(self) -> int:
        limit = self._data.get(FUNNEL_CORRELATION_PERSON_LIMIT)
        return int(limit) if limit else 0

    @cached_property
    def correlation_person_offset(self) -> int:
        offset = self._data.get(FUNNEL_CORRELATION_PERSON_OFFSET)
        return int(offset) if offset else 0

    @cached_property
    def correlation_persons_converted(self) -> Optional[bool]:
        converted = self._data.get(FUNNEL_CORRELATION_PERSON_CONVERTED)
        if not converted:
            return None
        if converted.lower() == "true":
            return True
        return False

    @include_dict
    def funnel_correlation_persons_to_dict(self):
        result_dict: Dict = {}
        if self.correlation_person_entity:
            result_dict[FUNNEL_CORRELATION_PERSON_ENTITY] = self.correlation_person_entity.to_dict()
        if self.correlation_property_values:
            result_dict[FUNNEL_CORRELATION_PROPERTY_VALUES] = [
                prop.to_dict() for prop in self.correlation_property_values
            ]
        if self.correlation_person_limit:
            result_dict[FUNNEL_CORRELATION_PERSON_LIMIT] = self.correlation_person_limit
        if self.correlation_person_offset:
            result_dict[FUNNEL_CORRELATION_PERSON_OFFSET] = self.correlation_person_offset
        if self.correlation_persons_converted is not None:
            result_dict[FUNNEL_CORRELATION_PERSON_CONVERTED] = self.correlation_persons_converted
        return result_dict
