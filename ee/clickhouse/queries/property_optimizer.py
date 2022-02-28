from typing import Dict, List, Optional, Set, Tuple, Union, cast

from rest_framework.exceptions import ValidationError

from posthog.constants import PropertyOperatorType
from posthog.models import Filter
from posthog.models.entity import Entity
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.property import Property, PropertyGroup


class PropertyOptimizer:
    """
    This class is responsible for figuring out what person or group properties can and should be pushed down to their
    respective tables in the query filter.

    This speeds up queries since clickhouse ends up selecting less data.
    """

    def __init__(self, filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter], team_id: int):
        self.filter = filter
        self.team_id = team_id

    @cached_property
    def property_groups(self):
        property_group = self.filter.property_groups
        return self._parse_property_groups(property_group)

    def _parse_property_groups(
        self, property_group: PropertyGroup
    ) -> Tuple[Optional[PropertyGroup], Optional[PropertyGroup]]:
        " Returns outer and inner property groups for persons"
        # TODO: handle cohorts?

        if len(property_group.values) == 0:
            return None, None

        # If all person properties, push them down
        if property_group.type == PropertyOperatorType.OR:
            # with OR'ed properties, we can't push properties down,
            # unless they're all person properties
            if self.using_only_person_properties(property_group):
                return None, property_group
            else:
                return property_group, None

        else:
            # Top level type is AND.
            # If all person properties, push them down
            if self.using_only_person_properties(property_group):
                return None, property_group
            else:
                # Mixed, look into each individual group
                if isinstance(property_group.values[0], PropertyGroup):
                    # multiple nested property groups
                    # we care about selecting AND groups with person properties
                    outer_property_group_values = []
                    inner_property_group_values = []
                    for group in property_group.values:
                        assert isinstance(group, PropertyGroup)

                        outer, inner = self._parse_property_groups(group)
                        if outer:
                            outer_property_group_values.append(outer)

                        if inner:
                            inner_property_group_values.append(inner)

                    return (
                        PropertyGroup(PropertyOperatorType.AND, outer_property_group_values),
                        PropertyGroup(PropertyOperatorType.AND, inner_property_group_values),
                    )

                elif isinstance(property_group.values[0], Property):
                    # list of properties that have been AND'ed, safe to push
                    # all person properties down, rest go to outer group
                    outer_property_values = []
                    inner_property_values = []
                    for property in property_group.values:
                        assert isinstance(property, Property)

                        if property.type == "person":
                            inner_property_values.append(property)
                        else:
                            outer_property_values.append(property)
                    return (
                        PropertyGroup(PropertyOperatorType.AND, outer_property_values),
                        PropertyGroup(PropertyOperatorType.AND, inner_property_values),
                    )

                else:
                    raise ValidationError("Invalid property group values")

    @staticmethod
    def using_only_person_properties(property_group: PropertyGroup) -> bool:
        if len(property_group.values) == 0:
            return True

        if isinstance(property_group.values[0], Property):
            return all(property.type == "person" for property in property_group.values)

        elif isinstance(property_group.values[0], PropertyGroup):
            return all(
                PropertyOptimizer.using_only_person_properties(group)
                for group in cast(List[PropertyGroup], property_group.values)
            )

        else:
            raise ValidationError("Invalid property group values")
