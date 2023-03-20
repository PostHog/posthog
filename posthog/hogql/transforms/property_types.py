from typing import Dict, Set

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


def resolve_property_types(node: ast.Expr, context: HogQLContext = None) -> ast.Expr:
    from posthog.models import PropertyDefinition

    # find all properties
    property_finder = PropertyFinder()
    property_finder.visit(node)

    # fetch them
    event_property_values = (
        PropertyDefinition.objects.filter(
            name__in=property_finder.event_properties,
            team_id=context.team_id,
            type__in=[None, PropertyDefinition.Type.EVENT],
        ).values_list("name", "property_type")
        if property_finder.event_properties
        else []
    )
    event_properties = {name: property_type for name, property_type in event_property_values if property_type}

    person_property_values = (
        PropertyDefinition.objects.filter(
            name__in=property_finder.person_properties,
            team_id=context.team_id,
            type=PropertyDefinition.Type.PERSON,
        ).values_list("name", "property_type")
        if property_finder.person_properties
        else []
    )
    person_properties = {name: property_type for name, property_type in person_property_values if property_type}

    # swap them out
    if len(event_properties) == 0 and len(person_properties) == 0:
        return node
    property_swapper = PropertySwapper(event_properties=event_properties, person_properties=person_properties)
    return property_swapper.visit(node)


class PropertyFinder(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.person_properties: Set[str] = set()
        self.event_properties: Set[str] = set()

    def visit_property_ref(self, node: ast.PropertyRef):
        if node.parent.name == "properties":
            if isinstance(node.parent.table, ast.BaseTableRef):
                table = node.parent.table.resolve_database_table().hogql_table()
                if table == "persons":
                    self.person_properties.add(node.name)
                if table == "events":
                    self.event_properties.add(node.name)


class PropertySwapper(CloningVisitor):
    def __init__(self, event_properties: Dict[str, str], person_properties: Dict[str, str]):
        super().__init__(clear_refs=False)
        self.event_properties = event_properties
        self.person_properties = person_properties

    def visit_field(self, node: ast.Field):
        ref = node.ref
        if isinstance(ref, ast.PropertyRef) and ref.parent.name == "properties":
            if isinstance(ref.parent.table, ast.BaseTableRef):
                table = ref.parent.table.resolve_database_table().hogql_table()
                if table == "persons":
                    if ref.name in self.person_properties:
                        return self._add_type_to_string_field(node, self.person_properties[ref.name])
                if table == "events":
                    if ref.name in self.event_properties:
                        return self._add_type_to_string_field(node, self.event_properties[ref.name])
        return node

    def _add_type_to_string_field(self, node: ast.Field, type: str):
        if type == "DateTime":
            return ast.Call(name="toDateTime", args=[node])
        if type == "Numeric":
            return ast.Call(name="toFloat", args=[node])
        if type == "Boolean":
            return parse_expr("{node} = 'true'", {"node": node})
        return node
