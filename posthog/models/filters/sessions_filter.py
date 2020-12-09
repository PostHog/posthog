from typing import Any, Dict, Optional

from django.http import HttpRequest

from posthog.constants import DISTINCT_ID_FILTER
from posthog.models.filters.filter import Filter

RETENTION_DEFAULT_INTERVALS = 11


class SessionsFilter(Filter):
    distinct_id: Optional[str]

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        super().__init__(data, request, **kwargs)
        if request:
            data = {
                **request.GET.dict(),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")

        self.distinct_id = data.get(DISTINCT_ID_FILTER)
