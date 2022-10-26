from posthog.models import Filter
from posthog.models.filters.mixins.session_recordings import (
    PersonUUIDMixin,
    SessionRecordingsMetadataMixin,
    SessionRecordingsMixin,
)


class SessionRecordingsFilter(SessionRecordingsMixin, SessionRecordingsMetadataMixin, PersonUUIDMixin, Filter):
    pass
