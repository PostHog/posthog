from posthog.models import Filter
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import DateMixin
from posthog.models.filters.mixins.sessions import DistinctIdMixin, PaginationMixin, SessionsFiltersMixin


class SessionsFilter(SessionsFiltersMixin, DistinctIdMixin, PaginationMixin, Filter):
    @property
    def limit_by_recordings(self) -> bool:
        return self.duration_filter_property is not None


class SessionEventsFilter(DistinctIdMixin, DateMixin, BaseFilter):
    pass
