import json
from typing import Dict, List, Optional, Union, cast

from posthog.constants import (
    DISTINCT_ID_FILTER,
    SESSIONS_FILTER_ACTION_TYPE,
    SESSIONS_FILTER_COHORT_TYPE,
    SESSIONS_FILTER_EVENT_TYPE,
    SESSIONS_FILTER_PERSON_TYPE,
    SESSIONS_FILTER_RECORDING_TYPE,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.models.entity import Entity
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict
from posthog.models.property import Property


class DistinctIdMixin(BaseParamMixin):
    @cached_property
    def distinct_id(self) -> Optional[str]:
        return self._data.get(DISTINCT_ID_FILTER, None)

    @include_dict
    def distinct_id_to_dict(self):
        return {"distinct_id": self.distinct_id} if self.distinct_id else {}


class PaginationMixin(BaseParamMixin):
    @cached_property
    def pagination(self) -> Dict:
        _pagination = self._data.get("pagination", {})
        return json.loads(_pagination) if isinstance(_pagination, str) else _pagination

    @include_dict
    def pagination_to_dict(self):
        return {"pagination": self.pagination}


class SessionsFiltersMixin(BaseParamMixin):
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
    def person_filter_properties(self) -> List[Property]:
        return [
            Property(**filter)
            for filter in self._all_filters
            if filter["type"] in [SESSIONS_FILTER_COHORT_TYPE, SESSIONS_FILTER_PERSON_TYPE]
        ]

    @cached_property
    def duration_filter_property(self) -> Optional[Property]:
        return next(
            (
                Property(**filter)
                for filter in self._all_filters
                if filter["type"] == SESSIONS_FILTER_RECORDING_TYPE and filter["key"] == "duration"
            ),
            None,
        )

    @cached_property
    def _all_filters(self) -> List[Dict]:
        _props = self._data.get("filters")
        return json.loads(_props) if isinstance(_props, str) else _props or []

    @include_dict
    def filters_to_dict(self):
        return {"filters": self._all_filters}
