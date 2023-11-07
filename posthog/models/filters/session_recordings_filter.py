from .filter import Filter
from .mixins.session_recordings import PersonUUIDMixin, SessionRecordingsMixin


class SessionRecordingsFilter(SessionRecordingsMixin, PersonUUIDMixin, Filter):
    pass
