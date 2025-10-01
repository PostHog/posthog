from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

from posthog.schema import PropertyOperator

from posthog.constants import PropertyOperatorType
from posthog.models.property import GroupTypeIndex, PropertyGroup

if TYPE_CHECKING:  # Avoid circular import
    from posthog.models import Property, Team

T = TypeVar("T")


class SimplifyFilterMixin:
    # :KLUDGE: A lot of this logic ignores typing since generics w/ mixins are hard to get working properly
    def simplify(self: T, team: "Team", **kwargs) -> T:
        """
        Expands this filter to not refer to external resources of the team.

        Actions taken:
        - if filter.filter_test_accounts, adds property filters to `filter.properties`
        - if aggregating by groups, adds property filter to remove blank groups
        - for cohort properties, replaces them with more concrete lookups or with cohort conditions
        """
        if self._data.get("is_simplified"):
            return self

        # :TRICKY: Make a copy to avoid caching issues
        result: Any = self.shallow_clone({"is_simplified": True})

        if getattr(result, "filter_test_accounts", False):
            new_group = {"type": "AND", "values": team.test_account_filters}
            prop_group = (
                {"type": "AND", "values": [new_group, result.property_groups.to_dict()]}
                if result.property_groups.to_dict()
                else new_group
            )
            result = result.shallow_clone({"properties": prop_group, "filter_test_accounts": False})

        updated_entities = {}
        if hasattr(result, "entities_to_dict"):
            for entity_type, entities in result.entities_to_dict().items():
                updated_entities[entity_type] = [
                    self._simplify_entity(team, entity_type, entity, **kwargs) for entity in entities
                ]

        from posthog.models.property.util import clear_excess_levels

        prop_group = clear_excess_levels(
            self._simplify_property_group(team, result.property_groups, **kwargs),
            skip=True,
        )
        prop_group = prop_group.to_dict()

        new_group_props = []
        if getattr(result, "aggregation_group_type_index", None) is not None:
            new_group_props.append(self._group_set_property(cast(int, result.aggregation_group_type_index)).to_dict())

        if new_group_props:
            new_group = {"type": "AND", "values": new_group_props}
            prop_group = {"type": "AND", "values": [new_group, prop_group]} if prop_group else new_group

        return result.shallow_clone({**updated_entities, "properties": prop_group})

    def _simplify_entity(
        self,
        team: "Team",
        entity_type: Literal["events", "actions", "exclusions"],
        entity_params: dict,
        **kwargs,
    ) -> dict:
        from posthog.models.entity import Entity, ExclusionEntity

        EntityClass = ExclusionEntity if entity_type == "exclusions" else Entity

        entity = EntityClass(entity_params)
        # TODO: when we support AND-ORs in entities, unflatten them here
        properties = self._simplify_properties(team, entity.property_groups.flat, **kwargs).flat
        if entity.math == "unique_group":
            properties.append(self._group_set_property(cast(GroupTypeIndex, entity.math_group_type_index)))

        return EntityClass({**entity_params, "properties": properties}).to_dict()

    def _simplify_properties(self, team: "Team", properties: list["Property"], **kwargs) -> "PropertyGroup":
        simplified_properties_values = []
        for prop in properties:
            simplified_properties_values.append(self._simplify_property(team, prop, **kwargs))
        return PropertyGroup(type=PropertyOperatorType.AND, values=simplified_properties_values)

    def _simplify_property_group(self, team: "Team", prop_group: "PropertyGroup", **kwargs) -> "PropertyGroup":
        from posthog.models.property import Property, PropertyGroup

        new_groups = []
        for group in prop_group.values:
            if isinstance(group, PropertyGroup):
                new_groups.append(self._simplify_property_group(team, group))
            elif isinstance(group, Property):
                new_groups.append(self._simplify_property(team, group))

        prop_group.values = new_groups
        return prop_group

    def _simplify_property(self, team: "Team", property: "Property", **kwargs) -> "PropertyGroup":
        if property.type == "cohort":
            from posthog.models import Cohort
            from posthog.models.cohort.util import simplified_cohort_filter_properties

            try:
                cohort = Cohort.objects.get(pk=property.value, team__project_id=team.project_id)
            except Cohort.DoesNotExist:
                # :TODO: Handle non-existing resource in-query instead
                return PropertyGroup(type=PropertyOperatorType.AND, values=[property])

            return simplified_cohort_filter_properties(
                cohort, team, property.negation or property.operator == PropertyOperator.NOT_IN.value
            )

        # PropertyOperatorType doesn't really matter here, since only one value.
        return PropertyGroup(type=PropertyOperatorType.AND, values=[property])

    def _group_set_property(self, group_type_index: GroupTypeIndex) -> "Property":
        from posthog.models.property import Property

        return Property(key=f"$group_{group_type_index}", value="", operator="is_not")

    @property
    def is_simplified(self) -> bool:
        return self._data.get("is_simplified", False)
