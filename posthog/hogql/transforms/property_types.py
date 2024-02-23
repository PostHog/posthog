from typing import Dict, Set, Literal, Optional, cast

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DateTimeDatabaseField
from posthog.hogql.escape_sql import escape_hogql_identifier
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor
from posthog.models.property import PropertyName, TableColumn
from posthog.utils import PersonOnEventsMode


def resolve_property_types(node: ast.Expr, context: Optional[HogQLContext] = None) -> ast.Expr:
    from posthog.models import PropertyDefinition

    if not context or not context.team_id:
        return node

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

    group_properties = {}
    for group_id, properties in property_finder.group_properties.items():
        if not properties:
            continue
        group_property_values = PropertyDefinition.objects.filter(
            name__in=properties,
            team_id=context.team_id,
            type=PropertyDefinition.Type.GROUP,
            group_type_index=group_id,
        ).values_list("name", "property_type")
        group_properties.update(
            {f"{group_id}_{name}": property_type for name, property_type in group_property_values if property_type}
        )

    # swap them out
    if (
        len(event_properties) == 0
        and len(person_properties) == 0
        and len(group_properties) == 0
        and not property_finder.found_timestamps
    ):
        return node

    timezone = context.database.get_timezone() if context and context.database else "UTC"
    property_swapper = PropertySwapper(
        timezone=timezone,
        event_properties=event_properties,
        person_properties=person_properties,
        group_properties=group_properties,
        context=context,
    )
    return property_swapper.visit(node)


class PropertyFinder(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.person_properties: Set[str] = set()
        self.event_properties: Set[str] = set()
        self.group_properties: Dict[int, Set[str]] = {}
        self.found_timestamps = False

    def visit_property_type(self, node: ast.PropertyType):
        if node.field_type.name == "properties" and len(node.chain) == 1:
            if isinstance(node.field_type.table_type, ast.BaseTableType):
                table_type = node.field_type.table_type
                table_name = table_type.resolve_database_table().to_printed_hogql()
                property_name = str(node.chain[0])
                if table_name == "persons" or table_name == "raw_persons":
                    self.person_properties.add(property_name)
                if table_name == "groups":
                    if isinstance(table_type, ast.LazyJoinType):
                        if table_type.field.startswith("group_"):
                            group_id = int(table_type.field.split("_")[1])
                            if self.group_properties.get(group_id) is None:
                                self.group_properties[group_id] = set()
                            self.group_properties[group_id].add(property_name)
                if table_name == "events":
                    if (
                        isinstance(node.field_type.table_type, ast.VirtualTableType)
                        and node.field_type.table_type.field == "poe"
                    ):
                        self.person_properties.add(property_name)
                    else:
                        self.event_properties.add(property_name)

    def visit_field(self, node: ast.Field):
        super().visit_field(node)
        if isinstance(node.type, ast.FieldType) and isinstance(
            node.type.resolve_database_field(), DateTimeDatabaseField
        ):
            self.found_timestamps = True


class PropertySwapper(CloningVisitor):
    def __init__(
        self,
        timezone: str,
        event_properties: Dict[str, str],
        person_properties: Dict[str, str],
        group_properties: Dict[str, str],
        context: HogQLContext,
    ):
        super().__init__(clear_types=False)
        self.timezone = timezone
        self.event_properties = event_properties
        self.person_properties = person_properties
        self.group_properties = group_properties
        self.context = context

    def visit_field(self, node: ast.Field):
        if isinstance(node.type, ast.FieldType):
            if isinstance(node.type.resolve_database_field(), DateTimeDatabaseField):
                return ast.Call(
                    name="toTimeZone",
                    args=[node, ast.Constant(value=self.timezone)],
                    type=ast.CallType(
                        name="toTimeZone",
                        arg_types=[ast.DateTimeType()],
                        return_type=ast.DateTimeType(),
                    ),
                )

        type = node.type
        if isinstance(type, ast.PropertyType) and type.field_type.name == "properties" and len(type.chain) == 1:
            property_name = str(type.chain[0])
            if (
                isinstance(type.field_type.table_type, ast.VirtualTableType)
                and type.field_type.table_type.field == "poe"
            ):
                if property_name in self.person_properties:
                    return self._convert_string_property_to_type(node, "person", property_name)
            elif isinstance(type.field_type.table_type, ast.BaseTableType):
                table_type = type.field_type.table_type
                table_name = table_type.resolve_database_table().to_printed_hogql()
                if table_name == "persons" or table_name == "raw_persons":
                    if property_name in self.person_properties:
                        return self._convert_string_property_to_type(node, "person", property_name)
                if table_name == "groups":
                    if isinstance(table_type, ast.LazyJoinType):
                        if table_type.field.startswith("group_"):
                            group_id = int(table_type.field.split("_")[1])
                            if f"{group_id}_{property_name}" in self.group_properties:
                                return self._convert_string_property_to_type(
                                    node, "group", f"{group_id}_{property_name}"
                                )
                if table_name == "events":
                    if property_name in self.event_properties:
                        return self._convert_string_property_to_type(node, "event", property_name)
        if isinstance(type, ast.PropertyType) and type.field_type.name == "person_properties" and len(type.chain) == 1:
            property_name = str(type.chain[0])
            if isinstance(type.field_type.table_type, ast.BaseTableType):
                table = type.field_type.table_type.resolve_database_table().to_printed_hogql()
                if table == "events":
                    if property_name in self.person_properties:
                        return self._convert_string_property_to_type(node, "person", property_name)

        return node

    def _convert_string_property_to_type(
        self,
        node: ast.Field,
        property_type: Literal["event", "person", "group"],
        property_name: str,
    ):
        if property_type == "person":
            posthog_field_type = self.person_properties.get(property_name)
        elif property_type == "group":
            posthog_field_type = self.group_properties.get(property_name)
        else:
            posthog_field_type = self.event_properties.get(property_name)

        field_type = "Float" if posthog_field_type == "Numeric" else posthog_field_type or "String"
        self._add_property_notice(node, property_type, field_type)

        if field_type == "DateTime":
            return ast.Call(name="toDateTime", args=[node])
        if field_type == "Float":
            return ast.Call(name="toFloat", args=[node])
        if field_type == "Boolean":
            return ast.Call(
                name="transform",
                args=[
                    node,
                    ast.Constant(value=["true", "false"]),
                    ast.Constant(value=[True, False]),
                    ast.Constant(value=None),
                ],
            )
        return node

    def _add_property_notice(
        self,
        node: ast.Field,
        property_type: Literal["event", "person", "group"],
        field_type: str,
    ):
        property_name = str(node.chain[-1])
        if property_type == "person":
            if self.context.modifiers.personsOnEventsMode != PersonOnEventsMode.DISABLED:  # type: ignore[comparison-overlap]
                materialized_column = self._get_materialized_column("events", property_name, "person_properties")
            else:
                materialized_column = self._get_materialized_column("person", property_name, "properties")  # type: ignore[unreachable]
        elif property_type == "group":
            name_parts = property_name.split("_")
            name_parts.pop(0)
            property_name = "_".join(name_parts)
            materialized_column = self._get_materialized_column("groups", property_name, "properties")
        else:
            materialized_column = self._get_materialized_column("events", property_name, "properties")

        message = f"{property_type.capitalize()} property '{property_name}' is of type '{field_type}'."
        if self.context.debug:
            if materialized_column:
                message += " This property is materialized ⚡️."
            else:
                message += " This property is not materialized 🐢."

        self._add_notice(node=node, message=message)

    def _add_notice(self, node: ast.Field, message: str):
        if node.start is None or node.end is None:
            return  # Don't add notices for nodes without location (e.g. from EventsQuery JSON)
        # Only highlight the last part of the chain
        self.context.add_notice(
            start=max(node.start, node.end - len(escape_hogql_identifier(node.chain[-1]))),
            end=node.end,
            message=message,
        )

    def _get_materialized_column(
        self, table_name: str, property_name: PropertyName, field_name: TableColumn
    ) -> Optional[str]:
        try:
            from ee.clickhouse.materialized_columns.columns import (
                TablesWithMaterializedColumns,
                get_materialized_columns,
            )

            materialized_columns = get_materialized_columns(cast(TablesWithMaterializedColumns, table_name))
            return materialized_columns.get((property_name, field_name), None)
        except ModuleNotFoundError:
            return None
