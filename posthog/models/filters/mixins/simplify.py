from typing import TYPE_CHECKING, Any, List, TypeVar

from posthog.utils import is_clickhouse_enabled

if TYPE_CHECKING:  # Avoid circular import
    from posthog.models import Property, Team

T = TypeVar("T")


class SimplifyFilterMixin:
    def simplify(self: T, team: "Team") -> T:
        """
        Expands this filter to not refer to external resources of the team.

        Actions taken:
        - if filter.filter_test_accounts, adds property filters to `filter.properties`
        - expands cohort filters
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

        simplified_properties = [self.simplified_property(prop) for prop in result.properties]

        return result.with_data({"properties": simplified_properties, "is_simplified": True,})

    def simplify_property(
        self, team: "Team", property: "Property", is_clickhouse_enabled=is_clickhouse_enabled()
    ) -> List[Property]:
        if property.type == "cohort" and is_clickhouse_enabled:
            from ee.clickhouse.models.cohort import simplified_cohort_filter_properties
            from posthog.models.filters import Filter

            # :TODO: Handle cohort not existing
            cohort = Cohort.objects.get(pk=property.value, team_id=team.pk)

            return simplified_cohort_filter_properties(cohort, team)

        return [property]

    @property
    def is_simplified(self) -> bool:
        return self._data.get("is_simplified", False)  # type: ignore
