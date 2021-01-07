import json
from typing import Dict, List, Optional, Union, cast

from posthog.constants import (
    DISTINCT_ID_FILTER,
    SESSIONS_FILTER_ACTION_TYPE,
    SESSIONS_FILTER_COHORT_TYPE,
    SESSIONS_FILTER_EVENT_TYPE,
    SESSIONS_FILTER_PERSON_TYPE,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.models.entity import Entity
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict
from posthog.models.property import Property


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


class SessionsFiltersMixin(BaseParamMixin):
    @cached_property
    def _all_filters(self) -> List[Dict]:
        _props = self._data.get("filters")
        return json.loads(_props) if isinstance(_props, str) else _props

    @cached_property
    def action_filters(self) -> List[Entity]:
        TYPE_MAPPING = {
            SESSIONS_FILTER_ACTION_TYPE: TREND_FILTER_TYPE_ACTIONS,
            SESSIONS_FILTER_EVENT_TYPE: TREND_FILTER_TYPE_EVENTS,
        }
        return [
            Entity({**filter, "id": filter["value"], "type": TYPE_MAPPING[filter["type"]]})
            for filter in self._all_filters
            if filter["type"] in [SESSIONS_FILTER_ACTION_TYPE, SESSIONS_FILTER_EVENT_TYPE]
        ]

    @cached_property
    def action_filter(self) -> Optional[Entity]:
        return self.action_filters[0] if len(self.action_filters) > 0 else None

    @cached_property
    def person_filter_properties(self) -> Optional[Property]:
        return [
            Property(**filter)
            for filter in self._all_filters
            if filter["type"] in [SESSIONS_FILTER_COHORT_TYPE, SESSIONS_FILTER_PERSON_TYPE]
        ]
