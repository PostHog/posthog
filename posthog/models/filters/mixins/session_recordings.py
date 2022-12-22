import json
from typing import List, Optional

from posthog.constants import (
    PERSON_UUID_FILTER,
    SESSION_RECORDINGS_FILTER_STATIC_RECORDINGS,
    SESSION_RECORDINGS_FILTER_TYPE_DURATION,
)
from posthog.session_recordings.session_recording_helpers import MinimalStaticSessionRecording
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
    def static_recordings(self) -> Optional[List[MinimalStaticSessionRecording]]:
        static_recordings_str = self._data.get(SESSION_RECORDINGS_FILTER_STATIC_RECORDINGS, None)
        if static_recordings_str is None:
            return None

        static_recordings = json.loads(static_recordings_str)
        return [
            MinimalStaticSessionRecording(id=recording.get("id", None), created_at=recording.get("created_at", None))
            for recording in static_recordings
        ]
