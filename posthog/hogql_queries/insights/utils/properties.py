from typing import TypeGuard

from posthog.schema import PropertyGroupFilter, PropertyGroupFilterValue

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.insights.query_context import QueryContext
from posthog.types import AnyPropertyFilter

type PropertiesType = list[AnyPropertyFilter] | PropertyGroupFilter | None


def has_any_property_filters(properties: object) -> TypeGuard[list[AnyPropertyFilter] | PropertyGroupFilter]:
    """Check if properties contain any actual filter values, not just empty group structure."""
    if isinstance(properties, PropertyGroupFilter):
        return any(has_any_property_filters_in_group(value) for value in properties.values)
    if isinstance(properties, list):
        return len(properties) > 0
    return bool(properties)


def has_any_property_filters_in_group(group: PropertyGroupFilterValue) -> bool:
    if not group.values:
        return False

    for value in group.values:
        if isinstance(value, PropertyGroupFilterValue):
            if has_any_property_filters_in_group(value):
                return True
        else:
            return True

    return False


class Properties:
    context: QueryContext

    def __init__(
        self,
        context: QueryContext,
    ) -> None:
        self.context = context

    def to_exprs(self) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []

        team, query = self.context.team, self.context.query

        # Filter Test Accounts
        if (
            query.filterTestAccounts
            and isinstance(team.test_account_filters, list)
            and len(team.test_account_filters) > 0
        ):
            for property in team.test_account_filters:
                exprs.append(property_to_expr(property, team))

        # Properties
        if has_any_property_filters(query.properties):
            exprs.append(property_to_expr(query.properties, team))

        return exprs
