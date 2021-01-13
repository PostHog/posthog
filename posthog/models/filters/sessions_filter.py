from typing import Any, Dict, Optional

from django.http import HttpRequest

from posthog.models import Filter
from posthog.models.filters.mixins.sessions import DistinctIdMixin, SessionsFiltersMixin


class SessionsFilter(SessionsFiltersMixin, DistinctIdMixin, Filter):
    def __init__(self, data: Dict[str, Any] = {}, request: Optional[HttpRequest] = None, **kwargs) -> None:
        super().__init__(data, request, **kwargs)

    @property
    def limit_by_recordings(self) -> bool:
        return self.duration_filter_property is not None
