from posthog.models import Filter
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import DateMixin
from posthog.models.filters.mixins.sessions import DistinctIdMixin, PaginationMixin, SessionsFiltersMixin, UserIdMixin


class SessionsFilter(SessionsFiltersMixin, DistinctIdMixin, PaginationMixin, UserIdMixin, Filter):
    @property
    def limit_by_recordings(self) -> bool:
        return self.recording_duration_filter is not None or self.recording_unseen_filter


class SessionEventsFilter(DistinctIdMixin, DateMixin, BaseFilter):
    pass
