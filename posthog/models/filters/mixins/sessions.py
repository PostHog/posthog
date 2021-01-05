from typing import Optional

from posthog.constants import DISTINCT_ID_FILTER
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict


class DurationMixin(BaseParamMixin):
    @cached_property
    def duration(self) -> float:
        return float(self._data.get("duration", "0"))

    @include_dict
    def duration_to_dict(self):
        return {"duration": self.duration} if self.duration else {}


class DurationOperatorMixin(BaseParamMixin):
    @cached_property
    def duration_operator(self) -> Optional[str]:
        return self._data.get("duration_operator", None)

    @include_dict
    def duration_operator_to_dict(self):
        return {"duration_operator": self.duration_operator} if self.duration_operator else {}


class DistinctIdMixin(BaseParamMixin):
    @cached_property
    def distinct_id(self) -> Optional[str]:
        return self._data.get(DISTINCT_ID_FILTER, None)

    @include_dict
    def distinct_id_to_dict(self):
        return {"distinct_id": self.distinct_id} if self.distinct_id else {}
