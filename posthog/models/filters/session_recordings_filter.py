from posthog.models import Filter
from posthog.models.filters.mixins.session_recordings import PersonUUIDMixin, SessionRecordingsMixin


class SessionRecordingsFilter(SessionRecordingsMixin, PersonUUIDMixin, Filter):
    pass
