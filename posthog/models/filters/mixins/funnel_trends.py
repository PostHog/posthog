from posthog.constants import FUNNEL_FROM_STEP, FUNNEL_TO_STEP
from posthog.models.filters.mixins.base import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict


class FunnelTrendsMixin(BaseParamMixin):
    @cached_property
    def funnel_from_step(self) -> int:
        from_step = int(self._data.get(FUNNEL_FROM_STEP, 1))
        return from_step

    @cached_property
    def funnel_to_step(self) -> int:
        to_step = int(self._data.get(FUNNEL_TO_STEP, len(self.entities)))
        return to_step

    @include_dict
    def funnel_window_days_to_dict(self):
        dict_part = {}
        if self.funnel_from_step:
            dict_part[FUNNEL_FROM_STEP] = self.funnel_from_step
        if self.funnel_to_step:
            dict_part[FUNNEL_TO_STEP] = self.funnel_to_step
        return dict_part
