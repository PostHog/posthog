from typing import TypeVar

from posthog.schema import HogQLVariable

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import CloningVisitor

from posthog.models.insight_variable import InsightVariable
from posthog.models.team.team import Team

T = TypeVar("T", bound=ast.Expr)


def replace_variables(node: T, variables: list[HogQLVariable], team: Team) -> T:
    return ReplaceVariables(variables, team).visit(node)


class ReplaceVariables(CloningVisitor):
    insight_variables: list[InsightVariable]

    def __init__(self, variables: list[HogQLVariable], team: Team):
        super().__init__()

        insight_vars = InsightVariable.objects.filter(team_id=team.pk, id__in=[v.variableId for v in variables]).all()

        self.insight_variables = list(insight_vars)
        self.variables = variables
        self.team = team

    def visit_placeholder(self, node):
        if node.chain and node.chain[0] == "variables":
            variable_code_name = node.chain[1]
            if not self.variables:
                raise QueryError(f"Variable {variable_code_name} is missing from query")

            matching_variables = [variable for variable in self.variables if variable.code_name == variable_code_name]
            if not matching_variables:
                raise QueryError(f"Variable {variable_code_name} is missing from query")

            matching_variable = matching_variables[0]

            matching_insight_variable = [
                variable for variable in self.insight_variables if variable.code_name == variable_code_name
            ]
            if not matching_insight_variable:
                raise QueryError(f"Variable {variable_code_name} does not exist")

            if matching_variable.isNull:
                return ast.Constant(value=None)

            value = (
                matching_variable.value
                if matching_variable.value is not None
                else matching_insight_variable[0].default_value
            )

            return ast.Constant(value=value)

        return super().visit_placeholder(node)
