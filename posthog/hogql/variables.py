import re
from difflib import get_close_matches
from typing import TypeVar

from posthog.schema import HogQLVariable

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import CloningVisitor

from posthog.models.team.team import Team
from posthog.utils import relative_date_parse

from products.product_analytics.backend.models.insight_variable import InsightVariable

T = TypeVar("T", bound=ast.Expr)


def replace_variables(node: T, variables: list[HogQLVariable], team: Team) -> T:
    replacer = ReplaceVariables(variables, team)
    result = replacer.visit(node)
    replacer.raise_for_missing_variables()
    return result


class ReplaceVariables(CloningVisitor):
    def __init__(self, variables: list[HogQLVariable], team: Team):
        super().__init__()

        self.variables = variables
        self.team = team
        self._insight_variables: list[InsightVariable] | None = None
        self.missing_variables: list[str] = []

    @property
    def insight_variables(self) -> list[InsightVariable]:
        # Loaded on the first {variables.*} placeholder so queries without variables run no query.
        # Keyed by code_name so a placeholder resolves from its default_value even when the request
        # omits the variable or carries a stale id that no longer points at a saved variable.
        if self._insight_variables is None:
            self._insight_variables = list(InsightVariable.objects.filter(team_id=self.team.pk))
        return self._insight_variables

    def visit_placeholder(self, node):
        if node.chain and node.chain[0] == "variables":
            variable_code_name = node.chain[1]

            matching_variable = next(
                (variable for variable in self.variables if variable.code_name == variable_code_name), None
            )
            variable_definition = next(
                (variable for variable in self.insight_variables if variable.code_name == variable_code_name), None
            )

            if matching_variable is not None and matching_variable.isNull:
                if (
                    variable_definition is not None
                    and variable_definition.type == InsightVariable.Type.LIST
                    and variable_definition.is_multi
                ):
                    return ast.Array(exprs=[])
                return ast.Constant(value=None)

            if matching_variable is not None and matching_variable.value is not None:
                value = matching_variable.value
            elif variable_definition is not None:
                # No value on the request, so fall back to the saved default (which may itself be None).
                value = variable_definition.default_value
            else:
                # Neither the request nor a saved variable can supply a value. Record the name and keep
                # visiting so every unresolved variable is reported in one error, not just the first.
                self.missing_variables.append(variable_code_name)
                return ast.Constant(value=None)

            if variable_definition is not None and variable_definition.type == InsightVariable.Type.LIST:
                if variable_definition.is_multi:
                    # Saved insights keep the scalar value from before a variable was
                    # toggled to multi — wrap it so {variables.x} is always an array.
                    items = value if isinstance(value, list) else ([] if value is None else [value])
                    return ast.Array(exprs=[ast.Constant(value=item) for item in items])
                if isinstance(value, list):
                    value = value[0] if value else None

            if (
                variable_definition is not None
                and variable_definition.type == InsightVariable.Type.DATE
                and isinstance(value, str)
                and is_relative_date_value(value)
            ):
                value = relative_date_parse(value, self.team.timezone_info)

            return ast.Constant(value=value)

        return super().visit_placeholder(node)

    def raise_for_missing_variables(self) -> None:
        if not self.missing_variables:
            return

        missing = sorted(set(self.missing_variables))
        # Keep the variable names in the trailing detail, not the leading sentence, so error tracking
        # groups every occurrence into one issue instead of one issue per variable name.
        detail = f"Missing: {', '.join(missing)}"
        suggestions = self._get_variable_suggestions(missing)
        if suggestions:
            detail += f". Did you mean: {', '.join(suggestions)}?"
        raise QueryError(f"Set a value or a default for each query variable. {detail}")

    def _get_variable_suggestions(self, missing_names: list[str]) -> list[str]:
        available_variables: list[str] = [str(variable.code_name) for variable in self.insight_variables]
        if not available_variables:
            return []
        matches = [
            match for name in missing_names for match in get_close_matches(name, available_variables, cutoff=0.6)
        ]
        return list(dict.fromkeys(matches))


def is_relative_date_value(value: str) -> bool:
    return re.fullmatch(r"-?\d*[hdwmqysHDWMQY](?:Start|End)?", value) is not None
