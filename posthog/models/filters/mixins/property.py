import json
from typing import Any, List, Optional, Union, cast

from rest_framework.exceptions import ValidationError

from posthog.constants import PROPERTIES, PROPERTY_GROUPS, PropertyOperatorType
from posthog.models.filters.mixins.base import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict
from posthog.models.property import Property, PropertyGroup


class PropertyMixin(BaseParamMixin):
    @cached_property
    def properties(self) -> List[Property]:
        _props = self._data.get(PROPERTIES)

        if isinstance(_props, str):
            try:
                loaded_props = json.loads(_props)
            except json.decoder.JSONDecodeError:
                raise ValidationError("Properties are unparsable!")
        else:
            loaded_props = _props

        return self._parse_properties(loaded_props)

    @cached_property
    def property_groups(self) -> PropertyGroup:
        _props = self._data.get(PROPERTY_GROUPS, None)

        if not _props:
            return PropertyGroup(type=PropertyOperatorType.AND, properties=self.properties)

        if isinstance(_props, str):
            try:
                loaded_props = json.loads(_props)
            except json.decoder.JSONDecodeError:
                raise ValidationError("Properties are unparsable!")
        else:
            loaded_props = _props

        return self._parse_grouped_properties(loaded_props)

    def _parse_properties(self, properties: Optional[Any]) -> List[Property]:
        if isinstance(properties, list):
            _properties = []
            for prop_params in properties:
                if isinstance(prop_params, Property):
                    _properties.append(prop_params)
                else:
                    try:
                        new_prop = Property(**prop_params)
                        _properties.append(new_prop)
                    except:
                        continue
            return _properties
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

    def _parse_grouped_properties(self, properties: Optional[Any]) -> PropertyGroup:
        if isinstance(properties, list):
            default_group = self._parse_properties(properties)
            return PropertyGroup(PropertyOperatorType.AND, default_group)

        elif isinstance(properties, dict):
            # TODO: what to do about old-old properties? Its been a year, safe to rm?
            if "type" in properties and "properties" in properties:
                return cast(PropertyGroup, self._parse_grouped_properties_recursively(properties))

        # TODO: empty case?
        props: Union[List[Property], List[PropertyGroup]] = []
        return PropertyGroup(PropertyOperatorType.AND, props)

    def _parse_grouped_properties_recursively(
        self, properties: Optional[Any]
    ) -> Union[List[Property], List[PropertyGroup], PropertyGroup]:
        # either get a list of properties or a dict representing a property group

        if not properties:
            # empty prop list
            props: Union[List[Property], List[PropertyGroup]] = []
            return props

        if isinstance(properties, list):
            # either a list of Property objects or a list of PropertyGroup objects
            props: Union[List[Property], PropertyGroup] = []

            if "type" in properties[0] and "properties" in properties[0]:
                # list of PropertyGroup objects
                # TODO: validate when list has both PropertyGroup and Property objects
                return [self._parse_grouped_properties_recursively(prop) for prop in properties]
            else:
                return self._parse_properties(properties)

        elif "type" in properties and "properties" in properties:
            props = self._parse_grouped_properties_recursively(properties["properties"])
            # TODO: error when invalid type
            return PropertyGroup(properties["type"], props)

        return []

    @include_dict
    def properties_to_dict(self):
        # TODO: add groups
        return {"properties": [prop.to_dict() for prop in self.properties]} if self.properties else {}
