from dataclasses import dataclass
from difflib import get_close_matches

from posthog.schema import HogQLNotice

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

from posthog.models import EventDefinition, PropertyDefinition, Team


@dataclass(frozen=True)
class TaxonomyReference:
    name: str
    start: int | None = None
    end: int | None = None


class TaxonomyReferenceVisitor(TraversingVisitor):
    def __init__(self):
        self.event_literals: list[TaxonomyReference] = []
        self.property_names: list[TaxonomyReference] = []

    def visit_compare_operation(self, node: ast.CompareOperation):
        self._collect_event_comparison(node)
        super().visit_compare_operation(node)

    def visit_field(self, node: ast.Field):
        self._collect_property_field(node)
        super().visit_field(node)

    def visit_array_access(self, node: ast.ArrayAccess):
        self._collect_property_array_access(node)
        super().visit_array_access(node)

    def _collect_event_comparison(self, node: ast.CompareOperation) -> None:
        if node.op == ast.CompareOperationOp.Eq:
            reference = _event_literal_from_equality(node.left, node.right) or _event_literal_from_equality(
                node.right, node.left
            )
            if reference:
                self.event_literals.append(reference)
            return

        if node.op in {ast.CompareOperationOp.In, ast.CompareOperationOp.GlobalIn} and _is_event_field(node.left):
            self.event_literals.extend(_string_literals_from_array(node.right))

    def _collect_property_field(self, node: ast.Field) -> None:
        if len(node.chain) >= 2 and node.chain[0] == "properties" and isinstance(node.chain[1], str):
            self.property_names.append(TaxonomyReference(node.chain[1], node.start, node.end))

    def _collect_property_array_access(self, node: ast.ArrayAccess) -> None:
        if (
            _is_properties_field(node.array)
            and isinstance(node.property, ast.Constant)
            and isinstance(node.property.value, str)
        ):
            self.property_names.append(TaxonomyReference(node.property.value, node.property.start, node.property.end))


def validate_taxonomy_references(
    query: ast.SelectQuery | ast.SelectSetQuery, team: Team, table_names: list[str] | None = None
) -> list[HogQLNotice]:
    visitor = TaxonomyReferenceVisitor()
    visitor.visit(query)

    if table_names is not None and "events" not in table_names:
        return []

    if not visitor.event_literals and not visitor.property_names:
        return []

    warnings: list[HogQLNotice] = []

    if visitor.event_literals:
        event_names = set(EventDefinition.objects.filter(team=team).values_list("name", flat=True))
        warnings.extend(_warnings_for_unknown_references("Event", visitor.event_literals, event_names))

    if visitor.property_names:
        property_names = set(
            PropertyDefinition.objects.filter(team=team, type=PropertyDefinition.Type.EVENT).values_list(
                "name", flat=True
            )
        )
        warnings.extend(_warnings_for_unknown_references("Property", visitor.property_names, property_names))

    return warnings


def _is_event_field(node: ast.Expr) -> bool:
    return isinstance(node, ast.Field) and node.chain in (["event"], ["events", "event"])


def _is_properties_field(node: ast.Expr) -> bool:
    return isinstance(node, ast.Field) and len(node.chain) == 1 and node.chain[0] == "properties"


def _event_literal_from_equality(field_node: ast.Expr, value_node: ast.Expr) -> TaxonomyReference | None:
    if not _is_event_field(field_node):
        return None
    if not isinstance(value_node, ast.Constant) or not isinstance(value_node.value, str):
        return None
    return TaxonomyReference(value_node.value, value_node.start, value_node.end)


def _string_literals_from_array(node: ast.Expr) -> list[TaxonomyReference]:
    if not isinstance(node, (ast.Array, ast.Tuple)):
        return []

    references: list[TaxonomyReference] = []
    for expr in node.exprs:
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            references.append(TaxonomyReference(expr.value, expr.start, expr.end))
    return references


def _warnings_for_unknown_references(
    kind: str, references: list[TaxonomyReference], known_names: set[str]
) -> list[HogQLNotice]:
    if not known_names:
        return []

    warnings: list[HogQLNotice] = []
    seen: set[str] = set()

    for reference in references:
        if reference.name in known_names or reference.name in seen:
            continue
        seen.add(reference.name)

        suggestion = _suggest_name(reference.name, known_names)
        message = f"{kind} '{reference.name}' was not found in this project taxonomy."
        if suggestion:
            message += f" Did you mean '{suggestion}'?"

        warnings.append(
            HogQLNotice(
                message=message,
                start=reference.start,
                end=reference.end,
                fix=suggestion,
            )
        )

    return warnings


def _suggest_name(name: str, known_names: set[str]) -> str | None:
    dollar_prefixed = f"${name}"
    if not name.startswith("$") and dollar_prefixed in known_names:
        return dollar_prefixed

    matches = get_close_matches(name, sorted(known_names), n=1, cutoff=0.6)
    return matches[0] if matches else None
