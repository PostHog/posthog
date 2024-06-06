import json
from typing import Optional

from posthog.constants import PERSON_UUID_FILTER, SESSION_RECORDINGS_FILTER_IDS
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property import Property, PropertyGroup


class PersonUUIDMixin(BaseParamMixin):
    @cached_property
    def person_uuid(self) -> Optional[str]:
        return self._data.get(PERSON_UUID_FILTER, None)


class SessionRecordingsMixin(BaseParamMixin):
    @cached_property
    def console_logs(self) -> list[PropertyGroup]:
        user_value = self._data.get("console_logs", None) or []
        if isinstance(user_value, str):
            user_value = json.loads(user_value)
        return [PropertyGroup(group["type"], group["values"]) for group in user_value]

    @cached_property
    def duration(self) -> Optional[list[Property]]:
        duration_filters_data_str = self._data.get("duration", None)
        if duration_filters_data_str:
            filter_array = json.loads(duration_filters_data_str)
            return [Property(**filter) for filter in filter_array]
        return None

    @cached_property
    def session_ids(self) -> Optional[list[str]]:
        # Can be ['a', 'b'] or "['a', 'b']" or "a,b"
        session_ids_str = self._data.get(SESSION_RECORDINGS_FILTER_IDS, None)

        if session_ids_str is None:
            return None

        if isinstance(session_ids_str, list):
            recordings_ids = session_ids_str
        elif isinstance(session_ids_str, str):
            if session_ids_str.startswith("["):
                recordings_ids = json.loads(session_ids_str)
            else:
                recordings_ids = session_ids_str.split(",")

        if all(isinstance(recording_id, str) for recording_id in recordings_ids):
            # Sort for stable queries
            return sorted(recordings_ids)

        # If the property is at all present, we assume that the user wants to filter by it
        return []
