from posthog.models import Filter
from posthog.models.filters.mixins.sessions import DistinctIdMixin


class SessionRecordingsFilter(DistinctIdMixin, Filter):
    pass
