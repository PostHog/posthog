import re
from difflib import get_close_matches
from typing import TypeVar

from posthog.schema import HogQLVariable

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import CloningVisitor

from posthog.models.team.team import Team
from posthog.utils import relative_date_parse

from products.product_analytics.backend.facade.api import insight_variables_by_ids
from products.product_analytics.backend.facade.contracts import InsightVariableDefinition
from products.product_analytics.backend.facade.enums import InsightVariableType

T = TypeVar("T", bound=ast.Expr)

# Argument positions that must hold an array. A single-select list variable substitutes as a
# scalar, so ClickHouse rejects the generated SQL with a type error that never names the variable.
_ARRAY_ARGUMENT_POSITIONS: dict[str, tuple[int, ...]] = {
    "has": (0,),
    "hasall": (0, 1),
    "hasany": (0, 1),
    "indexof": (0,),
    "arrayelement": (0,),
    "arrayjoin": (0,),
}


def replace_variables(node: T, variables: list[HogQLVariable], team: Team) -> T:
    return ReplaceVariables(variables, team).visit(node)


class ReplaceVariables(CloningVisitor):
    insight_variables: list[InsightVariableDefinition]

    def __init__(self, variables: list[HogQLVariable], team: Team):
        super().__init__()

        self.insight_variables = insight_variables_by_ids(team.pk, [v.variableId for v in variables])
        self.variables = variables
        self.team = team

    def visit_call(self, node: ast.Call) -> ast.Expr:
        for position in _ARRAY_ARGUMENT_POSITIONS.get(node.name.lower(), ()):
            if position < len(node.args):
                self._check_array_argument(node.args[position], node.name)
        return super().visit_call(node)

    def _check_array_argument(self, argument: ast.Expr, function_name: str) -> None:
        chain = argument.chain if isinstance(argument, ast.Placeholder) else None
        if not chain or len(chain) < 2 or chain[0] != "variables":
            return

        variable_code_name = str(chain[1])
        definition = next((v for v in self.insight_variables if v.code_name == variable_code_name), None)
        if definition is None or definition.type != InsightVariableType.LIST or definition.is_multi:
            return

        raise QueryError(
            f"Variable {variable_code_name} holds a single value, but {function_name}() needs a list. "
            f"Set the variable to allow multiple values, or pass an array instead."
        )

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

            variable_definition = matching_insight_variable[0]
            if matching_variable.isNull:
                if variable_definition.type == InsightVariableType.LIST and variable_definition.is_multi:
                    return ast.Array(exprs=[])
                return ast.Constant(value=None)

            value = (
                matching_variable.value
                if matching_variable.value is not None
                else matching_insight_variable[0].default_value
            )

            if variable_definition.type == InsightVariableType.LIST:
                if variable_definition.is_multi:
                    # Saved insights keep the scalar value from before a variable was
                    # toggled to multi — wrap it so {variables.x} is always an array.
                    items = value if isinstance(value, list) else ([] if value is None else [value])
                    return ast.Array(exprs=[ast.Constant(value=item) for item in items])
                if not variable_definition.is_multi and isinstance(value, list):
                    value = value[0] if value else None

            if (
                variable_definition.type == InsightVariableType.DATE
                and isinstance(value, str)
                and is_relative_date_value(value)
            ):
                value = relative_date_parse(value, self.team.timezone_info)

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


def is_relative_date_value(value: str) -> bool:
    return re.fullmatch(r"-?\d*[hdwmqysHDWMQY](?:Start|End)?", value) is not None
