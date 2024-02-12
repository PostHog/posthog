from copy import copy
from typing import Callable, Dict, List, Optional, cast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    LazyJoin,
    LazyTable,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    VirtualTable,
)
from posthog.hogql.filters import replace_filters
from posthog.hogql.functions.mapping import ALL_EXPOSED_FUNCTION_NAMES
from posthog.hogql.parser import parse_select
from posthog.hogql import ast
from posthog.hogql.base import AST, CTE, ConstantType
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor
from posthog.models.property_definition import PropertyDefinition
from posthog.models.team.team import Team
from posthog.schema import (
    HogQLAutocomplete,
    HogQLAutocompleteResponse,
    AutocompleteCompletionItem,
    Kind,
)


class GetNodeAtPositionTraverser(TraversingVisitor):
    start: int
    end: int
    selects: List[ast.SelectQuery] = []
    node: Optional[AST] = None
    parent_node: Optional[AST] = None
    last_node: Optional[AST] = None
    nearest_select_query: Optional[ast.SelectQuery] = None

    def __init__(self, expr: ast.Expr, start: int, end: int):
        super().__init__()
        self.start = start
        self.end = end
        super().visit(expr)

    def visit(self, node: AST):
        if node is not None and node.start is not None and node.end is not None:
            if self.start >= node.start and self.end <= node.end:
                self.node = node
                self.parent_node = self.last_node
                self.nearest_select_query = self.selects[-1]

        self.last_node = node
        super().visit(node)

    def visit_select_query(self, node):
        self.selects.append(node)
        node = super().visit_select_query(node)
        self.selects.pop()


def constant_type_to_database_field(constant_type: ConstantType, name: str) -> DatabaseField:
    if isinstance(constant_type, ast.BooleanType):
        return BooleanDatabaseField(name=name)
    if isinstance(constant_type, ast.IntegerType):
        return IntegerDatabaseField(name=name)
    if isinstance(constant_type, ast.FloatType):
        return FloatDatabaseField(name=name)
    if isinstance(constant_type, ast.StringType):
        return StringDatabaseField(name=name)
    if isinstance(constant_type, ast.DateTimeType):
        return DateTimeDatabaseField(name=name)
    if isinstance(constant_type, ast.DateType):
        return DateDatabaseField(name=name)

    return DatabaseField(name=name)


def get_table(context: HogQLContext, join_expr: ast.JoinExpr, ctes: Optional[Dict[str, CTE]]) -> None | Table:
    assert context.database is not None

    def resolve_fields_on_table(table: Table | None, table_query: ast.SelectQuery) -> Table | None:
        # Resolve types and only return selected fields
        if table is None:
            return None

        try:
            node = cast(ast.SelectQuery, resolve_types(node=table_query, dialect="hogql", context=context))
            if node.type is None:
                return None

            selected_columns = node.type.columns
            new_fields: Dict[str, FieldOrTable] = {}
            for name, field in selected_columns.items():
                if isinstance(field, ast.FieldAliasType):
                    underlying_field_name = field.alias
                    if isinstance(field.type, ast.FieldAliasType):
                        underlying_field_name = field.type.alias
                    elif isinstance(field.type, ast.ConstantType):
                        constant_field = constant_type_to_database_field(field.type, name)
                        new_fields[name] = constant_field
                        continue
                    elif isinstance(field, ast.FieldType):
                        underlying_field_name = field.name
                    else:
                        underlying_field_name = name
                elif isinstance(field, ast.FieldType):
                    underlying_field_name = field.name
                else:
                    underlying_field_name = name

                new_fields[name] = table.fields[underlying_field_name]

            table_name = table.to_printed_hogql()

            # Return a new table with a reduced field set
            class AnonTable(Table):
                fields: Dict[str, FieldOrTable] = new_fields

                def to_printed_hogql(self):
                    # Use the base table name for resolving property definitions later
                    return table_name

            return AnonTable()
        except Exception:
            return None

    if isinstance(join_expr.table, ast.Field):
        table_name = str(join_expr.table.chain[0])
        if ctes is not None:
            # Handle CTEs
            cte = ctes.get(table_name)
            if cte is not None:
                if cte.cte_type == "subquery" and isinstance(cte.expr, ast.SelectQuery):
                    query = cast(ast.SelectQuery, cte.expr)
                    if query.select_from is not None:
                        table = get_table(context, query.select_from, ctes)
                        return resolve_fields_on_table(table, query)

        # Handle a base table
        if context.database.has_table(table_name):
            return context.database.get_table(table_name)
    elif isinstance(join_expr.table, ast.SelectQuery):
        if join_expr.table.select_from is None:
            return None

        # Recursively get the base table
        underlying_table = get_table(context, join_expr.table.select_from, ctes)

        if underlying_table is None:
            return None

        return resolve_fields_on_table(underlying_table, join_expr.table)
    return None


def extend_responses(
    keys: List[str],
    suggestions: List[AutocompleteCompletionItem],
    kind: Kind = Kind.Variable,
    insert_text: Optional[Callable[[str], str]] = None,
) -> None:
    suggestions.extend(
        [
            AutocompleteCompletionItem(
                insertText=insert_text(key) if insert_text is not None else key,
                label=key,
                kind=kind,
            )
            for key in keys
        ]
    )


MATCH_ANY_CHARACTER = "$$_POSTHOG_ANY_$$"
PROPERTY_DEFINITION_LIMIT = 220


# TODO: Support ast.SelectUnionQuery nodes
def get_hogql_autocomplete(query: HogQLAutocomplete, team: Team) -> HogQLAutocompleteResponse:
    response = HogQLAutocompleteResponse(suggestions=[])

    database = create_hogql_database(team_id=team.pk, team_arg=team)
    context = HogQLContext(team_id=team.pk, team=team, database=database)

    original_query_select = copy(query.select)
    original_end_position = copy(query.endPosition)

    for extra_characters, length_to_add in [
        ("", 0),
        (MATCH_ANY_CHARACTER, len(MATCH_ANY_CHARACTER)),
        (" FROM events", 0),
        (f"{MATCH_ANY_CHARACTER} FROM events", len(MATCH_ANY_CHARACTER)),
    ]:
        try:
            query.select = (
                original_query_select[:original_end_position]
                + extra_characters
                + original_query_select[original_end_position:]
            )
            query.endPosition = original_end_position + length_to_add

            select_ast = parse_select(query.select)
            if query.filters:
                select_ast = cast(ast.SelectQuery, replace_filters(select_ast, query.filters, team))

            if isinstance(select_ast, ast.SelectQuery):
                ctes = select_ast.ctes
            else:
                ctes = select_ast.select_queries[0].ctes

            find_node = GetNodeAtPositionTraverser(select_ast, query.startPosition, query.endPosition)
            node = find_node.node
            parent_node = find_node.parent_node
            nearest_select = find_node.nearest_select_query or select_ast

            table_has_alias = (
                nearest_select is not None
                and isinstance(nearest_select, ast.SelectQuery)
                and nearest_select.select_from is not None
                and nearest_select.select_from.alias is not None
            )

            if (
                isinstance(node, ast.Field)
                and isinstance(nearest_select, ast.SelectQuery)
                and nearest_select.select_from is not None
                and not isinstance(parent_node, ast.JoinExpr)
            ):
                # TODO: add logic for FieldTraverser field types

                # Handle fields
                table = get_table(context, nearest_select.select_from, ctes)
                if table is None:
                    continue

                chain_len = len(node.chain)
                last_table: Table = table
                for index, chain_part in enumerate(node.chain):
                    # Return just the table alias
                    if table_has_alias and index == 0 and chain_len == 1:
                        extend_responses([str(chain_part)], response.suggestions, Kind.Folder)
                        break

                    if table_has_alias and index == 0:
                        continue

                    # Ignore last chain part, it's likely an incomplete word or added characters
                    is_last_part = index >= (chain_len - 2)

                    if is_last_part:
                        if last_table.fields.get(str(chain_part)) is None:
                            fields = list(table.fields.keys())
                            extend_responses(fields, response.suggestions)

                            available_functions = ALL_EXPOSED_FUNCTION_NAMES
                            extend_responses(
                                available_functions,
                                response.suggestions,
                                Kind.Function,
                                insert_text=lambda key: f"{key}()",
                            )
                            break

                        field = last_table.fields[str(chain_part)]

                        if isinstance(field, StringJSONDatabaseField):
                            if last_table.to_printed_hogql() == "events":
                                property_type = PropertyDefinition.Type.EVENT
                            elif last_table.to_printed_hogql() == "persons":
                                property_type = PropertyDefinition.Type.PERSON
                            elif last_table.to_printed_hogql() == "groups":
                                property_type = PropertyDefinition.Type.GROUP
                            else:
                                property_type = None

                            if property_type is not None:
                                match_term = query.select[query.startPosition : query.endPosition]
                                if match_term == MATCH_ANY_CHARACTER:
                                    match_term = ""

                                properties = PropertyDefinition.objects.filter(
                                    name__contains=match_term,
                                    team_id=team.pk,
                                    type=property_type,
                                )[:PROPERTY_DEFINITION_LIMIT].values("name")

                                extend_responses([prop["name"] for prop in properties], response.suggestions)
                        elif isinstance(field, VirtualTable) or isinstance(field, LazyTable):
                            fields = list(last_table.fields.keys())
                            extend_responses(fields, response.suggestions)
                        elif isinstance(field, LazyJoin):
                            fields = list(field.join_table.fields.keys())
                            extend_responses(fields, response.suggestions)
                        break
                    else:
                        field = last_table.fields[str(chain_part)]
                        if isinstance(field, Table):
                            last_table = field
                        elif isinstance(field, LazyJoin):
                            last_table = field.join_table
            elif isinstance(node, ast.Field) and isinstance(parent_node, ast.JoinExpr):
                # Handle table names
                if len(node.chain) == 1:
                    table_names = database.get_all_tables()
                    extend_responses(table_names, response.suggestions, Kind.Folder)
        except Exception:
            pass

        if len(response.suggestions) != 0:
            break

    return response
