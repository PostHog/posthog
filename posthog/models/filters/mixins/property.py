from functools import cached_property

from posthog.constants import PROPERTIES
from posthog.models.filters.mixins.base import BaseParamMixin
from posthog.models.property import PropertyGroup
from posthog.models.property.parse import parse_property_group_data


class PropertyMixin(BaseParamMixin):
    @cached_property
    def property_groups(self) -> PropertyGroup:
        return self._parse_data(key=PROPERTIES)

    def _parse_data(self, key: str) -> PropertyGroup:
        return parse_property_group_data(self._data.get(key))
