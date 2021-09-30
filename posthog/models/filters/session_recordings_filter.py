from posthog.models import Filter
from posthog.models.filters.mixins.session_recordings import DistinctIdMixin, SessionRecordingsMixin


class SessionRecordingsFilter(SessionRecordingsMixin, DistinctIdMixin, Filter):
    pass
