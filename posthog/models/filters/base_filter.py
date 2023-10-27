import inspect
import json
from typing import TYPE_CHECKING, Any, Dict, Optional

from rest_framework import request

from posthog.hogql.context import HogQLContext
from .mixins.common import BaseParamMixin
from posthog.models.utils import sane_repr
from posthog.utils import encode_get_request_params
from rest_framework.exceptions import ValidationError

from posthog.constants import PROPERTIES

if TYPE_CHECKING:
    from posthog.models.team.team import Team


class BaseFilter(BaseParamMixin):
    _data: Dict
    team: Optional["Team"]
    kwargs: Dict
    hogql_context: HogQLContext

    def __init__(
        self,
        data: Optional[Dict[str, Any]] = None,
        request: Optional[request.Request] = None,
        *,
        team: Optional["Team"] = None,
        **kwargs,
    ) -> None:
        if request:
            properties = {}
            if request.GET.get(PROPERTIES):
                try:
                    properties = json.loads(request.GET[PROPERTIES])
                except json.decoder.JSONDecodeError:
                    raise ValidationError("Properties are unparsable!")
            elif request.data and request.data.get(PROPERTIES):
                properties = request.data[PROPERTIES]

            data = {
                **request.GET.dict(),
                **request.data,
                **(data if data else {}),
                **({PROPERTIES: properties}),
            }
        elif data is None:
            raise ValueError("You need to define either a data dict or a request")

        self._data = data
        self.kwargs = kwargs
        self.team = team

        # Set the HogQL context for the request
        self.hogql_context = self.kwargs.get(
            "hogql_context",
            HogQLContext(within_non_hogql_query=True, team_id=self.team.pk if self.team else None),
        )
        if self.team:
            self.hogql_context.person_on_events_mode = self.team.person_on_events_mode

        if self.team and hasattr(self, "simplify") and not getattr(self, "is_simplified", False):
            simplified_filter = self.simplify(self.team)  # type: ignore
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

    def shallow_clone(self, overrides: Dict[str, Any]):
        "Clone the filter's data while sharing the HogQL context"
        return type(self)(
            data={**self._data, **overrides},
            **{**self.kwargs, "team": self.team, "hogql_context": self.hogql_context},
        )

    def query_tags(self) -> Dict[str, Any]:
        ret = {}

        for _, func in inspect.getmembers(self, inspect.ismethod):
            if hasattr(func, "include_query_tags"):  # provided by @include_query_tags decorator
                ret.update(func())

        return ret

    __repr__ = sane_repr("_data", "kwargs", include_id=False)
