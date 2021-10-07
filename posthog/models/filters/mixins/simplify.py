from typing import TYPE_CHECKING, Any, Dict, List, TypeVar

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
        - for cohort properties, replaces them with more concrete lookups or with cohort conditions
        """

        result: Any = self
        if getattr(self, "filter_test_accounts", False):
            result = result.with_data(
                {
                    "properties": result.properties + team.test_account_filters,
                    "filter_test_accounts": False,
                    "is_simplified": True,
                }
            )

        updated_entities = {}
        if hasattr(result, "entities_to_dict"):
            for entity_type, entities in result.entities_to_dict().items():
                updated_entities[entity_type] = [self._simplify_entity(team, entity, **kwargs) for entity in entities]  # type: ignore

        return result.with_data(
            {
                **updated_entities,
                "properties": self._simplify_properties(team, result.properties, **kwargs),  # type: ignore
                "is_simplified": True,
            }
        )

    def _simplify_entity(self, team: "Team", entity_params: Dict, **kwargs) -> Dict:
        from posthog.models import Entity

        entity = Entity(entity_params)
        return Entity(
            {**entity_params, "properties": self._simplify_properties(team, entity.properties, **kwargs)}
        ).to_dict()

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

    @property
    def is_simplified(self) -> bool:
        return self._data.get("is_simplified", False)  # type: ignore
