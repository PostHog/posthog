from posthog.constants import FUNNEL_WINDOW
from posthog.models.filters.mixins.base import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict


class FunnelWindowMixin(BaseParamMixin):
    @cached_property
    def funnel_window(self) -> int:
        _days = int(self._data.get(FUNNEL_WINDOW, 7))
        _funnel_window = self._milliseconds_from_days(_days)
        return _funnel_window

    @include_dict
    def funnel_window_to_dict(self):
        return {"funnel_window": self.funnel_window} if self.funnel_window else {}

    @staticmethod
    def _milliseconds_from_days(days):
        second, minute, hour, day = [1000, 60, 60, 24]
        return second * minute * hour * day * days
