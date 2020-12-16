import json
from datetime import datetime
from typing import Any, Dict, Optional, Union

from django.http import HttpRequest

from posthog.models.entity import Entity
from posthog.models.filters.mixins.common import BaseParamMixin, DateMixin
from posthog.models.property import Property


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

    def to_dict(self) -> Dict[str, Any]:
        raise NotImplementedError("to_dict must be implemented for filters")

    def toJSON(self):
        return json.dumps(self.to_dict(), default=lambda o: o.__dict__, sort_keys=True, indent=4)


class SerializerWithDateMixin(DateMixin):
    def to_dict(self) -> Dict[str, Any]:
        ret = {}

        for key in dir(self):
            value = getattr(self, key)
            if key in [
                "entities",
                "determine_time_delta",
                "date_filter_Q",
                "custom_date_filter_Q",
                "properties_to_Q",
                "toJSON",
                "to_dict",
            ] or key.startswith("_"):
                continue
            if isinstance(value, list) and len(value) == 0:
                continue
            if not isinstance(value, list) and not value:
                continue
            if key == "date_from" and not self._date_from:
                continue
            if key == "date_to" and not self._date_to:
                continue
            if isinstance(value, datetime):
                value = value.isoformat()
            if not isinstance(value, (list, bool, int, float, str)):
                # Try to see if this object is json serializable
                try:
                    json.dumps(value)
                except:
                    continue
            if isinstance(value, Entity):
                value = value.to_dict()
            if key == "properties" and isinstance(value, list) and isinstance(value[0], Property):
                value = [prop.to_dict() for prop in value]
            if isinstance(value, list) and isinstance(value[0], Entity):
                value = [entity.to_dict() for entity in value]
            ret[key] = value

        return ret
