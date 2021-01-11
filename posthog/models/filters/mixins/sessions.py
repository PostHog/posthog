import json
from typing import Dict, Optional, Union, cast

from posthog.constants import DISTINCT_ID_FILTER
from posthog.models.entity import Entity
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


class ActionFilterMixin(BaseParamMixin):
    @cached_property
    def action_filter(self) -> Optional[Entity]:
        if self._data.get("action_filter") is not None:
            action_filter = cast(Union[str, Dict], self._data.get("action_filter"))
            action_filter = json.loads(action_filter) if isinstance(action_filter, str) else action_filter
            return Entity(action_filter)
        else:
            return None
