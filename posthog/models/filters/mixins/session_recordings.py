import json
from typing import List, Optional, Literal

from posthog.constants import PERSON_UUID_FILTER, SESSION_RECORDINGS_FILTER_IDS
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property import Property


class PersonUUIDMixin(BaseParamMixin):
    @cached_property
    def person_uuid(self) -> Optional[str]:
        return self._data.get(PERSON_UUID_FILTER, None)


class SessionRecordingsMixin(BaseParamMixin):
    @cached_property
    def console_search_query(self) -> str | None:
        return self._data.get("console_search_query", None)

    @cached_property
    def console_logs_filter(self) -> List[Literal["error", "warn", "log"]]:
        user_value = self._data.get("console_logs", None) or []
        if isinstance(user_value, str):
            user_value = json.loads(user_value)
        valid_values = [x for x in user_value if x in ["error", "warn", "log"]]
        return valid_values

    @cached_property
    def duration_type_filter(self) -> Literal["duration", "active_seconds", "inactive_seconds"]:
        user_value = self._data.get("duration_type_filter", None)
        if user_value in ["duration", "active_seconds", "inactive_seconds"]:
            return user_value
        else:
            return "duration"

    @cached_property
    def recording_duration_filter(self) -> Optional[Property]:
        duration_filter_data_str = self._data.get("session_recording_duration", None)
        if duration_filter_data_str:
            filter_data = json.loads(duration_filter_data_str)
            return Property(**filter_data)
        return None

    @cached_property
    def session_ids(self) -> Optional[List[str]]:
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
