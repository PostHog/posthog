import inspect
import json
from typing import Any, Dict, Optional

from rest_framework import request

from posthog.hogql.hogql import HogQLContext
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.hogql import HogQLParamMixin
from posthog.models.utils import sane_repr
from posthog.utils import encode_get_request_params


class BaseFilter(BaseParamMixin, HogQLParamMixin):
    def __init__(
        self,
        data: Optional[Dict[str, Any]] = None,
        request: Optional[request.Request] = None,
        hogql_context: Optional[HogQLContext] = None,
        **kwargs,
    ) -> None:
        if request:
            data = {**request.GET.dict(), **request.data, **(data if data else {})}
        elif not data:
            raise ValueError("You need to define either a data dict or a request")
        self._data = data
        self.hogql_context = hogql_context or HogQLContext()
        self.kwargs = kwargs
        if kwargs.get("team"):
            self.team = kwargs["team"]

        if "team" in kwargs and hasattr(self, "simplify") and not getattr(self, "is_simplified", False):
            simplified_filter = self.simplify(kwargs["team"])  # type: ignore
            self._data = simplified_filter._data

    def to_dict(self) -> Dict[str, Any]:
        ret = {}

        for _, func in inspect.getmembers(self, inspect.ismethod):
            if hasattr(func, "include_dict"):  # provided by @include_dict decorator
                ret.update(func())

        return ret

    def to_params(self) -> Dict[str, str]:
        return encode_get_request_params(data=self.to_dict())

    def toJSON(self):
        return json.dumps(self.to_dict(), default=lambda o: o.__dict__, sort_keys=True, indent=4)

    def with_data(self, overrides: Dict[str, Any]):
        "Allow making copy of filter whilst preserving the class"
        return type(self)(data={**self._data, **overrides}, hogql_context=self.hogql_context, **self.kwargs)

    def query_tags(self) -> Dict[str, Any]:
        ret = {}

        for _, func in inspect.getmembers(self, inspect.ismethod):
            if hasattr(func, "include_query_tags"):  # provided by @include_query_tags decorator
                ret.update(func())

        return ret

    __repr__ = sane_repr("_data", "kwargs", include_id=False)
