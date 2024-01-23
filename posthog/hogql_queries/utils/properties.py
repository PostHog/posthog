from typing import List
from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.models.team.team import Team
from posthog.schema import (
    CohortPropertyFilter,
    ElementPropertyFilter,
    EmptyPropertyFilter,
    EventPropertyFilter,
    FeaturePropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    PersonPropertyFilter,
    PropertyGroupFilter,
    RecordingDurationFilter,
    SessionPropertyFilter,
)

PropertiesType = (
    List[
        EventPropertyFilter
        | PersonPropertyFilter
        | ElementPropertyFilter
        | SessionPropertyFilter
        | CohortPropertyFilter
        | RecordingDurationFilter
        | GroupPropertyFilter
        | FeaturePropertyFilter
        | HogQLPropertyFilter
        | EmptyPropertyFilter
    ]
    | PropertyGroupFilter
    | None
)


class Properties:
    team: Team
    properties: PropertiesType
    filterTestAccounts: bool | None

    def __init__(
        self,
        team: Team,
        properties: PropertiesType,
        filterTestAccounts: bool | None,
    ) -> None:
        self.team = team
        self.properties = properties
        self.filterTestAccounts = filterTestAccounts

    def to_exprs(self) -> List[ast.Expr]:
        exprs: List[ast.Expr] = []

        # Filter Test Accounts
        if (
            self.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for property in self.team.test_account_filters:
                exprs.append(property_to_expr(property, self.team))

        # Properties
        if self.properties is not None and self.properties != []:
            exprs.append(property_to_expr(self.properties, self.team))

        return exprs
