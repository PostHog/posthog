from posthog.models import Filter
from posthog.models.filters.mixins.sessions import DistinctIdMixin, SessionsFiltersMixin


class SessionsFilter(SessionsFiltersMixin, DistinctIdMixin, Filter):
    @property
    def limit_by_recordings(self) -> bool:
        return self.duration_filter_property is not None
