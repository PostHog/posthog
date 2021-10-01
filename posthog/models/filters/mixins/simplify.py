from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:  # Avoid circular import
    from posthog.models.team import Team

T = TypeVar("T")


class SimplifyFilterMixin:
    def simplify(self: T, team: "Team") -> T:  # type: ignore
        """
        Expands this filter to not refer to external resources of the team.

        Actions taken:
        - if filter.filter_test_accounts, adds property filters to `filter.properties`
        """

        result = self
        if getattr(self, "filter_test_accounts", False):
            result = result.with_data(
                {"properties": result.properties + team.test_account_filters, "filter_test_accounts": False}
            )

        return result
