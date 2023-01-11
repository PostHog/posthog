import json
from typing import List, Optional

from posthog.constants import PERSON_UUID_FILTER, SESSION_RECORDINGS_FILTER_IDS, SESSION_RECORDINGS_FILTER_TYPE_DURATION
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
    def session_ids(self) -> Optional[List[str]]:
        session_ids_str = self._data.get(SESSION_RECORDINGS_FILTER_IDS, None)
        if session_ids_str is None:
            return None

        recordings_ids = json.loads(session_ids_str)
        if isinstance(recordings_ids, list) and all(isinstance(recording_id, str) for recording_id in recordings_ids):
            return recordings_ids
        return None
