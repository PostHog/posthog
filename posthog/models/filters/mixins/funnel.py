from typing import Optional

from posthog.constants import (
    DISPLAY,
    FUNNEL_FROM_STEP,
    FUNNEL_ORDER_TYPE,
    FUNNEL_STEP,
    FUNNEL_TO_STEP,
    FUNNEL_VIZ_TYPE,
    FUNNEL_WINDOW_DAYS,
    INSIGHT,
    INSIGHT_FUNNELS,
    TRENDS_LINEAR,
    FunnelOrderType,
    FunnelVizType,
)
from posthog.models.filters.mixins.base import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict


class FunnelFromToStepsMixin(BaseParamMixin):
    @cached_property
    def funnel_from_step(self) -> Optional[int]:
        if self._data.get(FUNNEL_FROM_STEP):
            return int(self._data[FUNNEL_FROM_STEP])
        return None

    @cached_property
    def funnel_to_step(self) -> Optional[int]:
        if self._data.get(FUNNEL_TO_STEP):
            return int(self._data[FUNNEL_TO_STEP])
        return None

    @include_dict
    def funnel_from_to_steps_to_dict(self):
        dict_part = {}
        if self.funnel_from_step:
            dict_part[FUNNEL_FROM_STEP] = self.funnel_from_step
        if self.funnel_to_step:
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


class FunnelPersonsStepMixin(BaseParamMixin):

    # first step is 0
    # -1 means dropoff into step 1
    @cached_property
    def funnel_step(self) -> Optional[int]:
        _step = int(self._data.get(FUNNEL_STEP, "0"))
        if _step == 0:
            return None
        return _step

    @include_dict
    def funnel_step_to_dict(self):
        return {FUNNEL_STEP: self.funnel_step} if self.funnel_step else {}


class FunnelTypeMixin(BaseParamMixin):
    @cached_property
    def funnel_order_type(self) -> Optional[FunnelOrderType]:
        return self._data.get(FUNNEL_ORDER_TYPE)

    @cached_property
    def funnel_viz_type(self) -> Optional[FunnelVizType]:
        funnel_viz_type = self._data.get(FUNNEL_VIZ_TYPE)
        if (
            not funnel_viz_type is None
            and self._data.get(INSIGHT) == INSIGHT_FUNNELS
            and self._data.get(DISPLAY) == TRENDS_LINEAR
        ):
            # Backwards compatibility
            # Before Filter.funnel_viz_type funnel trends were indicated by Filter.display being TRENDS_LINEAR
            return FunnelVizType.TRENDS
        return funnel_viz_type

    @include_dict
    def funnel_type_to_dict(self):
        result = {}
        if self.funnel_order_type:
            result[FUNNEL_ORDER_TYPE] = self.funnel_order_type
        if self.funnel_viz_type:
            result[FUNNEL_VIZ_TYPE] = self.funnel_viz_type
        return result
