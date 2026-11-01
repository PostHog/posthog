import re
from difflib import get_close_matches
from typing import Any, TypeVar

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


def replace_variables(node: T, variables: list[HogQLVariable], team: Team) -> T:
    return ReplaceVariables(variables, team).visit(node)


class ReplaceVariables(CloningVisitor):
    insight_variables: list[InsightVariableDefinition]

    def __init__(self, variables: list[HogQLVariable], team: Team):
        super().__init__()

        self.insight_variables = insight_variables_by_ids(team.pk, [v.variableId for v in variables])
        self.variables = variables
        self.team = team
        self._inside_placeholder = False

    def visit_placeholder(self, node):
        if node.chain and len(node.chain) > 1 and node.chain[0] == "variables":
            return self._resolve_variable(str(node.chain[1]))
        self._inside_placeholder = True
        try:
            return super().visit_placeholder(node)
        finally:
            self._inside_placeholder = False

    def visit_field(self, node):
        if self._inside_placeholder and len(node.chain) > 1 and node.chain[0] == "variables":
            matching_variable, _ = self._find_variable(str(node.chain[1]))
            return self._expression_value(matching_variable.value)
        return super().visit_field(node)

    def _resolve_variable(self, variable_code_name: str) -> ast.Expr:
        matching_variable, variable_definition = self._find_variable(variable_code_name)
        if matching_variable.isNull:
            if variable_definition.type == InsightVariableType.LIST and variable_definition.is_multi:
                return ast.Array(exprs=[])
            return ast.Constant(value=None)

        value = matching_variable.value if matching_variable.value is not None else variable_definition.default_value
        return self._coerce_value(variable_definition, value)

    def _find_variable(self, variable_code_name: str) -> tuple[HogQLVariable, InsightVariableDefinition]:
        if not self.variables:
            raise self._missing_variable_error(variable_code_name)

        matching_variables = [variable for variable in self.variables if variable.code_name == variable_code_name]
        if not matching_variables:
            raise self._missing_variable_error(variable_code_name)

        matching_insight_variable = [
            variable for variable in self.insight_variables if variable.code_name == variable_code_name
        ]
        if not matching_insight_variable:
            raise QueryError(f"Variable {variable_code_name} does not exist")

        return matching_variables[0], matching_insight_variable[0]

    def _expression_value(self, value: Any) -> ast.Expr:
        if isinstance(value, list):
            return ast.Array(exprs=[ast.Constant(value=item) for item in value])
        return ast.Constant(value=value)

    def _coerce_value(self, variable_definition: InsightVariableDefinition, value: Any) -> ast.Expr:
        if variable_definition.type == InsightVariableType.LIST:
            if variable_definition.is_multi:
                # Saved insights keep the scalar value from before a variable was
                # toggled to multi — wrap it so {variables.x} is always an array.
                items = value if isinstance(value, list) else ([] if value is None else [value])
                return ast.Array(exprs=[ast.Constant(value=item) for item in items])
            if isinstance(value, list):
                value = value[0] if value else None

        if (
            variable_definition.type == InsightVariableType.DATE
            and isinstance(value, str)
            and is_relative_date_value(value)
        ):
            value = relative_date_parse(value, self.team.timezone_info)

        return ast.Constant(value=value)

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
