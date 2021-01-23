import json
from typing import Any, List, Optional

from posthog.constants import PROPERTIES
from posthog.models.filters.mixins.base import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict
from posthog.models.property import Property


class PropertyMixin(BaseParamMixin):
    @cached_property
    def properties(self) -> List[Property]:
        _props = self._data.get(PROPERTIES)
        loaded_props = json.loads(_props) if isinstance(_props, str) else _props
        return self._parse_properties(loaded_props)

    def _parse_properties(self, properties: Optional[Any]) -> List[Property]:
        if isinstance(properties, list):
            return [Property(**property) for property in properties]
        if not properties:
            return []

        # old style dict properties
        ret = []
        for key, value in properties.items():
            key_split = key.split("__")
            ret.append(
                Property(
                    key=key_split[0], value=value, operator=key_split[1] if len(key_split) > 1 else None, type="event",
                )
            )
        return ret

    @include_dict
    def properties_to_dict(self):
        return {"properties": [prop.to_dict() for prop in self.properties]} if self.properties else {}
