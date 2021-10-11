import inspect
import json
from typing import Any, Dict, Optional

from rest_framework import request

from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.utils import sane_repr


class BaseFilter(BaseParamMixin):
    def __init__(
        self, data: Optional[Dict[str, Any]] = None, request: Optional[request.Request] = None, **kwargs
    ) -> None:
        if request:
            data = {
                **request.GET.dict(),
                **request.data,
                **(data if data else {}),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")
        self._data = data
        self.kwargs = kwargs

        if "team" in kwargs and hasattr(self, "simplify") and not getattr(self, "is_simplified", False):
            simplified_filter = getattr(self, "simplify")(kwargs["team"])
            self._data = simplified_filter._data

    def to_dict(self) -> Dict[str, Any]:
        ret = {}

        for _, func in inspect.getmembers(self, inspect.ismethod):
            if hasattr(func, "include_dict"):  # provided by @include_dict decorator
                ret.update(func())

        return ret

    def toJSON(self):
        return json.dumps(self.to_dict(), default=lambda o: o.__dict__, sort_keys=True, indent=4)

    def with_data(self, overrides: Dict[str, Any]):
        "Allow making copy of filter whilst preserving the class"
        return type(self)(data={**self._data, **overrides}, **self.kwargs)

    __repr__ = sane_repr("_data", "kwargs", include_id=False)
