import json
from typing import List, Optional

from posthog.constants import (
    PERSON_UUID_FILTER,
    SESSION_RECORDINGS_FILTER_TYPE_DURATION,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.models.entity import Entity
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property import Property


class PersonUUIDMixin(BaseParamMixin):
    @cached_property
    def person_uuid(self) -> Optional[str]:
        return self._data.get(PERSON_UUID_FILTER, None)


class SessionRecordingsMixin(BaseParamMixin):
    @cached_property
    def recording_duration_filter(self) -> Optional[Property]:
        duration_filter_data_str = self._data.get(SESSION_RECORDINGS_FILTER_TYPE_DURATION, None)
        if duration_filter_data_str:
            filter_data = json.loads(duration_filter_data_str)
            return Property(**filter_data)
        return None

    @cached_property
    def event_and_action_filters(self) -> List[Entity]:
        event_str = self._data.get(TREND_FILTER_TYPE_EVENTS, "[]")
        event_filters = json.loads(event_str)
        action_str = self._data.get(TREND_FILTER_TYPE_ACTIONS, "[]")
        action_filters = json.loads(action_str)
        filters = event_filters + action_filters
        entities = []
        for filter in filters:
            if filter["type"] in [TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS]:
                entities.append(Entity(filter))
        return entities
