from posthog.constants import FUNNEL_WINDOW_DAYS
from posthog.models.filters.mixins.base import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict


class FunnelWindowDaysMixin(BaseParamMixin):
    @cached_property
    def funnel_window_days(self) -> int:
        _days = int(self._data.get(FUNNEL_WINDOW_DAYS, 14))
        return _days

    @include_dict
    def funnel_window_days_to_dict(self):
        return {FUNNEL_WINDOW_DAYS: self.funnel_window_days} if self.funnel_window_days else {}

    @staticmethod
    def milliseconds_from_days(days):
        second, minute, hour, day = [1000, 60, 60, 24]
        return second * minute * hour * day * days
