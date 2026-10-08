import json
from typing import Optional

from rest_framework.exceptions import ValidationError

from posthog.constants import (
    FUNNEL_CORRELATION_EVENT_EXCLUDE_PROPERTY_NAMES,
    FUNNEL_CORRELATION_EVENT_NAMES,
    FUNNEL_CORRELATION_EXCLUDE_EVENT_NAMES,
    FUNNEL_CORRELATION_EXCLUDE_NAMES,
    FUNNEL_CORRELATION_NAMES,
    FUNNEL_CORRELATION_TYPE,
    FUNNEL_CUSTOM_STEPS,
    FUNNEL_FROM_STEP,
    FUNNEL_STEP,
    FUNNEL_TO_STEP,
    FUNNEL_WINDOW_INTERVAL,
    FUNNEL_WINDOW_INTERVAL_TYPES,
    FUNNEL_WINDOW_INTERVAL_UNIT,
    FunnelCorrelationType,
)
from posthog.models.filters.mixins.base import BaseParamMixin, FunnelWindowIntervalType
from posthog.models.filters.mixins.utils import cached_property, include_dict


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


class FunnelWindowMixin(BaseParamMixin):
    @cached_property
    def funnel_window_interval(self) -> Optional[int]:
        _amt = int(self._data.get(FUNNEL_WINDOW_INTERVAL, "0"))
        if _amt == 0:
            return None
        return _amt

    @cached_property
    def funnel_window_interval_unit(self) -> Optional[FunnelWindowIntervalType]:
        _unit = self._data.get(FUNNEL_WINDOW_INTERVAL_UNIT, None)
        return _unit.lower() if _unit is not None else _unit

    @include_dict
    def funnel_window_to_dict(self):
        dict_part: dict = {}
        if self.funnel_window_interval is not None:
            dict_part[FUNNEL_WINDOW_INTERVAL] = self.funnel_window_interval
        if self.funnel_window_interval_unit is not None:
            dict_part[FUNNEL_WINDOW_INTERVAL_UNIT] = self.funnel_window_interval_unit
        return dict_part

    def funnel_window_interval_unit_ch(self) -> FUNNEL_WINDOW_INTERVAL_TYPES:
        if self.funnel_window_interval_unit is None:
            return "DAY"

        if self.funnel_window_interval_unit == "second":
            return "SECOND"
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
    def funnel_custom_steps(self) -> list[int]:
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
    def correlation_property_names(self) -> list[str]:
        # Person Property names for which to run Person Properties correlation
        property_names = self._data.get(FUNNEL_CORRELATION_NAMES, [])
        if isinstance(property_names, str):
            return json.loads(property_names)
        return property_names

    @cached_property
    def correlation_property_exclude_names(self) -> list[str]:
        # Person Property names to exclude from Person Properties correlation
        property_names = self._data.get(FUNNEL_CORRELATION_EXCLUDE_NAMES, [])
        if isinstance(property_names, str):
            return json.loads(property_names)
        return property_names

    @cached_property
    def correlation_event_names(self) -> list[str]:
        # Event names for which to run EventWithProperties correlation
        event_names = self._data.get(FUNNEL_CORRELATION_EVENT_NAMES, [])
        if isinstance(event_names, str):
            return json.loads(event_names)
        return event_names

    @cached_property
    def correlation_event_exclude_names(self) -> list[str]:
        # Exclude event names from Event correlation
        property_names = self._data.get(FUNNEL_CORRELATION_EXCLUDE_EVENT_NAMES, [])
        if isinstance(property_names, str):
            return json.loads(property_names)
        return property_names

    @cached_property
    def correlation_event_exclude_property_names(self) -> list[str]:
        # Event Property names to exclude from EventWithProperties correlation
        property_names = self._data.get(FUNNEL_CORRELATION_EVENT_EXCLUDE_PROPERTY_NAMES, [])
        if isinstance(property_names, str):
            return json.loads(property_names)
        return property_names

    @include_dict
    def funnel_correlation_to_dict(self):
        result_dict: dict = {}
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
