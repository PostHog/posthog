import json
from typing import List, Optional

from posthog.constants import (
    PERSON_UUID_FILTER,
    SESSION_RECORDINGS_FILTER_TYPE_DURATION,
    SESSION_RECORDINGS_FILTER_TYPE_INCLUDE_METADATA_FOR_RECORDINGS,
)
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict
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


class SessionRecordingsMetadataMixin(BaseParamMixin):
    @cached_property
    def include_metadata_for_recordings(self) -> List[str]:
        return [
            recording_id
            for recording_id in json.loads(
                self._data.get(SESSION_RECORDINGS_FILTER_TYPE_INCLUDE_METADATA_FOR_RECORDINGS, "[]")
            )
            if recording_id
        ]

    @include_dict
    def include_metadata_for_recordings_to_dict(self):
        return (
            {"include_metadata_for_recordings": self.include_metadata_for_recordings}
            if self.include_metadata_for_recordings
            else {}
        )
