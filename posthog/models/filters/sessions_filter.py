import json
from typing import Any, Dict, Optional, Tuple

from django.http import HttpRequest

from posthog.constants import DISTINCT_ID_FILTER
from posthog.models import Filter


class SessionsFilter(Filter):
    distinct_id: Optional[str]
    duration: Optional[Tuple[str, int]]

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        super().__init__(data, request, **kwargs)
        if request:
            data = {
                **request.GET.dict(),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")

        self.distinct_id = data.get(DISTINCT_ID_FILTER)
        if "duration" in data:
            self.duration = json.loads(data["duration"])
        else:
            self.duration = None

    @property
    def limit_by_recordings(self):
        return self.duration is not None
