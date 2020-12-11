from typing import Any, Dict, Optional

from django.http import HttpRequest

from posthog.constants import DISTINCT_ID_FILTER
from posthog.models import Filter


class SessionsFilter(Filter):
    distinct_id: Optional[str]
    duration_operator: Optional[str]  # lt, gt
    _duration: Optional[str]

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        super().__init__(data, request, **kwargs)
        if request:
            data = {
                **request.GET.dict(),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")

        self.distinct_id = data.get(DISTINCT_ID_FILTER)
        self.duration_operator = data.get("duration_operator")
        self._duration = data.get("duration")

    @property
    def duration(self) -> float:
        return float(self._duration or 0)

    @property
    def limit_by_recordings(self) -> bool:
        return self.duration_operator is not None
