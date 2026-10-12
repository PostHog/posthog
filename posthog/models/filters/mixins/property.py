import json

from rest_framework.exceptions import ValidationError

from posthog.constants import PROPERTIES
from posthog.models.filters.mixins.base import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict, include_query_tags
from posthog.models.property import Property, PropertyGroup
from posthog.models.property.parse import parse_properties, parse_property_group_data


class PropertyMixin(BaseParamMixin):
    @cached_property
    def property_groups(self) -> PropertyGroup:
        return self._parse_data(key=PROPERTIES)

    def _parse_data(self, key: str) -> PropertyGroup:
        return parse_property_group_data(self._data.get(key))

    def old_properties(self, key: str) -> list[Property]:
        _props = self._data.get(key)

        if isinstance(_props, str):
            try:
                loaded_props = json.loads(_props)
            except json.decoder.JSONDecodeError:
                raise ValidationError("Properties are unparsable!")
        else:
            loaded_props = _props

        # if grouped properties
        if (isinstance(loaded_props, dict) and "type" in loaded_props and "values" in loaded_props) or isinstance(
            loaded_props, PropertyGroup
        ):
            # property_groups is main function from now on
            # TODO: this function will go away at end of migration
            return []
        else:
            # old style dict properties or a list of properties
            return parse_properties(loaded_props)

    @include_dict
    def properties_to_dict(self):
        return (
            {PROPERTIES: self.property_groups.to_dict()} if self.property_groups and self.property_groups.values else {}
        )

    @include_query_tags
    def properties_query_tags(self):
        filter_by_type = {prop.type for prop in self.property_groups.flat}
        for entity in getattr(self, "entities", []):
            filter_by_type |= {prop.type for prop in entity.property_groups.flat}

        return {"filter_by_type": list(filter_by_type)}

    @cached_property
    def has_hogql_property(self):
        return any(prop.type == "hogql" for prop in self.property_groups.flat)
