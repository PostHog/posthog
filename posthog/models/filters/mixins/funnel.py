import datetime
import json
from typing import Dict, List, Literal, Optional, Union

from rest_framework.exceptions import ValidationError

from posthog.constants import (
    BIN_COUNT,
    DISPLAY,
    DROP_OFF,
    ENTRANCE_PERIOD_START,
    FUNNEL_CORRELATION_NAMES,
    FUNNEL_CORRELATION_TYPE,
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
        _step = int(self._data.get(FUNNEL_STEP, "0"))
        if _step == 0:
            return None
        return _step

    @include_dict
    def funnel_step_to_dict(self):
        return {FUNNEL_STEP: self.funnel_step} if self.funnel_step else {}


class FunnelPersonsStepBreakdownMixin(BaseParamMixin):
    @cached_property
    def funnel_step_breakdown(self) -> Optional[Union[str, int]]:
        return self._data.get(FUNNEL_STEP_BREAKDOWN)

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
    def correlation_property_names(self) -> Optional[List[str]]:
        property_names = self._data.get(FUNNEL_CORRELATION_NAMES, [])
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
        return result_dict
