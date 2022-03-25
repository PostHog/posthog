from typing import cast

from posthog.constants import INTERVAL, SUPPORTED_INTERVAL_TYPES
from posthog.models.filters.mixins.base import BaseParamMixin, IntervalType
from posthog.models.filters.mixins.utils import cached_property, include_dict


class IntervalMixin(BaseParamMixin):
    """See https://clickhouse.tech/docs/en/sql-reference/data-types/special-data-types/interval/."""

    @cached_property
    def interval(self) -> IntervalType:
        interval_candidate = self._data.get(INTERVAL)
        if not interval_candidate:
            return "day"
        if not isinstance(interval_candidate, str):
            raise ValueError(f"Interval must be a string!")
        interval_candidate = interval_candidate.lower()
        if interval_candidate == "minute":
            return "hour"
        if interval_candidate not in SUPPORTED_INTERVAL_TYPES:
            raise ValueError(f"Interval {interval_candidate} does not belong to SUPPORTED_INTERVAL_TYPES!")
        return cast(IntervalType, interval_candidate)

    @include_dict
    def interval_to_dict(self):
        return {"interval": self.interval}
