from typing import TYPE_CHECKING, Any, Dict, List, Literal, TypeVar, cast

from posthog.models.property import GroupTypeIndex
from posthog.utils import is_clickhouse_enabled

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

        if self._data.get("is_simplified"):  # type: ignore
            return self

        # :TRICKY: Make a copy to avoid caching issues
        result: Any = self.with_data({"is_simplified": True})  # type: ignore
        if getattr(result, "filter_test_accounts", False):
            result = result.with_data(
                {"properties": result.properties + team.test_account_filters, "filter_test_accounts": False,}
            )

        updated_entities = {}
        if hasattr(result, "entities_to_dict"):
            for entity_type, entities in result.entities_to_dict().items():
                updated_entities[entity_type] = [self._simplify_entity(team, entity_type, entity, **kwargs) for entity in entities]  # type: ignore

        properties = self._simplify_properties(team, result.properties, **kwargs)  # type: ignore
        if getattr(result, "aggregation_group_type_index", None) is not None:
            properties.append(self._group_set_property(cast(int, result.aggregation_group_type_index)))  # type: ignore

        return result.with_data({**updated_entities, "properties": properties,})

    def _simplify_entity(
        self, team: "Team", entity_type: Literal["events", "actions", "exclusions"], entity_params: Dict, **kwargs
    ) -> Dict:
        from posthog.models.entity import Entity, ExclusionEntity

        EntityClass = ExclusionEntity if entity_type == "exclusions" else Entity

        entity = EntityClass(entity_params)
        properties = self._simplify_properties(team, entity.properties, **kwargs)
        if entity.math == "unique_group":
            properties.append(self._group_set_property(cast(GroupTypeIndex, entity.math_group_type_index)))

        return EntityClass({**entity_params, "properties": properties}).to_dict()

    def _simplify_properties(self, team: "Team", properties: List["Property"], **kwargs) -> List["Property"]:
        simplified_properties = []
        for prop in properties:
            simplified_properties.extend(self._simplify_property(team, prop, **kwargs))
        return simplified_properties

    def _simplify_property(
        self, team: "Team", property: "Property", is_clickhouse_enabled=is_clickhouse_enabled()
    ) -> List["Property"]:
        if property.type == "cohort" and is_clickhouse_enabled:
            from ee.clickhouse.models.cohort import simplified_cohort_filter_properties
            from posthog.models import Cohort

            try:
                cohort = Cohort.objects.get(pk=property.value, team_id=team.pk)
            except Cohort.DoesNotExist:
                # :TODO: Handle non-existing resource in-query instead
                return [property]

            return simplified_cohort_filter_properties(cohort, team)

        return [property]

    def _group_set_property(self, group_type_index: GroupTypeIndex) -> "Property":
        from posthog.models.property import Property

        return Property(key=f"$group_{group_type_index}", value="", operator="is_not",)

    @property
    def is_simplified(self) -> bool:
        return self._data.get("is_simplified", False)  # type: ignore
