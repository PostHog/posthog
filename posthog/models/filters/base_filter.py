import json
from typing import Any, Dict, Optional

from django.http import HttpRequest

from posthog.models.filters.mixins.common import BaseParamMixin


class BaseFilter(BaseParamMixin):
    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        if request:
            data = {
                **(data if data else {}),
                **request.GET.dict(),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")
        self._data = data

    def to_dict(self):
        raise NotImplementedError("filters must implement to_dict")

    def toJSON(self):
        return json.dumps(self.to_dict(), default=lambda o: o.__dict__, sort_keys=True, indent=4)
