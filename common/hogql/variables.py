from difflib import get_close_matches
from typing import Any, TypeVar

from common.hogql import ast
from common.hogql.dependencies import HogQLVariableProvider, InsightVariableDefinition
from common.hogql.errors import QueryError
from common.hogql.visitor import CloningVisitor

T = TypeVar("T", bound=ast.Expr)


def replace_variables(
    node: T,
    variables: list[Any],
    team: Any,
    *,
    variable_provider: HogQLVariableProvider,
) -> T:
    return ReplaceVariables(variables, team, variable_provider).visit(node)


class ReplaceVariables(CloningVisitor):
    insight_variables: list[InsightVariableDefinition]

    def __init__(self, variables: list[Any], team: Any, variable_provider: HogQLVariableProvider):
        super().__init__()

        self.insight_variables = variable_provider.list_insight_variables(
            team=team,
            variable_ids=[variable.variableId for variable in variables],
        )
        self.variables = variables
        self.team = team

    def visit_placeholder(self, node):
        if node.chain and node.chain[0] == "variables":
            variable_code_name = node.chain[1]
            if not self.variables:
                raise self._missing_variable_error(variable_code_name)

            matching_variables = [variable for variable in self.variables if variable.code_name == variable_code_name]
            if not matching_variables:
                raise self._missing_variable_error(variable_code_name)

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

    def _missing_variable_error(self, variable_code_name: str) -> QueryError:
        suggestions = self._get_variable_suggestions(variable_code_name)
        if suggestions:
            suggestion_list = ", ".join(suggestions)
            return QueryError(f"Variable {variable_code_name} is missing from query. Did you mean: {suggestion_list}?")
        return QueryError(f"Variable {variable_code_name} is missing from query")

    def _get_variable_suggestions(self, variable_code_name: str) -> list[str]:
        available_variables: list[str] = [str(variable.code_name) for variable in self.insight_variables if variable]
        if not available_variables:
            return []
        return get_close_matches(variable_code_name, available_variables, n=3, cutoff=0.6)
