from typing import List, TypeAlias
from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.insights.query_context import QueryContext
from posthog.schema import PropertyGroupFilter
from posthog.types import AnyPropertyFilter

PropertiesType: TypeAlias = List[AnyPropertyFilter] | PropertyGroupFilter | None


class Properties:
    context: QueryContext

    def __init__(
        self,
        context: QueryContext,
    ) -> None:
        self.context = context

    def to_exprs(self) -> List[ast.Expr]:
        exprs: List[ast.Expr] = []

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
        if query.properties is not None and query.properties != []:
            exprs.append(property_to_expr(query.properties, team))

        return exprs
