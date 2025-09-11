import json
from typing import Any, Optional, Union, cast

from rest_framework.exceptions import ValidationError

from posthog.constants import PROPERTIES, PropertyOperatorType
from posthog.models.filters.mixins.base import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict, include_query_tags
from posthog.models.property import Property, PropertyGroup


class PropertyMixin(BaseParamMixin):
    @cached_property
    def property_groups(self) -> PropertyGroup:
        return self._parse_data(key=PROPERTIES)

    def _parse_data(self, key: str) -> PropertyGroup:
        _props = self._data.get(key)

        if isinstance(_props, str):
            try:
                loaded_props = json.loads(_props)
            except json.decoder.JSONDecodeError:
                raise ValidationError("Data is unparsable!")
        else:
            loaded_props = _props

        # if grouped properties
        if isinstance(loaded_props, dict) and "type" in loaded_props and "values" in loaded_props:
            try:
                return self._parse_property_group(loaded_props)
            except ValidationError:
                raise
            except ValueError as e:
                raise ValidationError(f"PropertyGroup is unparsable: {e}")
        # already a PropertyGroup just return
        elif isinstance(loaded_props, PropertyGroup):
            return loaded_props

        # old properties
        return PropertyGroup(type=PropertyOperatorType.AND, values=self.old_properties(key=key))

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
            return self._parse_properties(loaded_props)

    def _parse_properties(self, properties: Optional[Any]) -> list[Property]:
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
                    key=key_split[0],
                    value=value,
                    operator=key_split[1] if len(key_split) > 1 else None,
                    type="event",
                )
            )
        return ret

    def _parse_property_group(self, group: Optional[dict]) -> PropertyGroup:
        if group and "type" in group and "values" in group:
            return PropertyGroup(
                PropertyOperatorType(group["type"].upper()),
                self._parse_property_group_list(group["values"]),
            )

        return PropertyGroup(PropertyOperatorType.AND, cast(list[Property], []))

    def _parse_property_group_list(self, prop_list: Optional[list]) -> Union[list[Property], list[PropertyGroup]]:
        if not prop_list:
            # empty prop list
            return cast(list[Property], [])
        has_property_groups = False
        has_simple_properties = False

        for prop in prop_list:
            if "type" in prop and "values" in prop:
                has_property_groups = True
            elif "key" in prop:
                has_simple_properties = True
            else:
                has_property_groups = True

        if has_simple_properties and has_property_groups:
            raise ValidationError("Property list cannot contain both PropertyGroup and Property objects")

        if has_property_groups:
            return [self._parse_property_group(group) for group in prop_list]
        else:
            return self._parse_properties(prop_list)

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
