from typing import Callable, List, Optional, cast
from posthog.hogql.database.database import Database, create_hogql_database
from posthog.hogql.database.models import (
    LazyJoin,
    LazyTable,
    StringJSONDatabaseField,
    Table,
    VirtualTable,
)
from posthog.hogql.filters import replace_filters
from posthog.hogql.functions.mapping import ALL_EXPOSED_FUNCTION_NAMES
from posthog.hogql.parser import parse_select
from posthog.hogql import ast
from posthog.hogql.base import AST
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


def get_table(database: Database, join_expr: ast.JoinExpr) -> None | Table:
    if isinstance(join_expr.table, ast.Field):
        table_name = str(join_expr.table.chain[0])
        if database.has_table(table_name):
            return database.get_table(table_name)
    return None


def extend_responses(
    keys: List[str],
    suggestions: List[AutocompleteCompletionItem],
    kind: Kind = Kind.Field,
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


def get_hogql_autocomplete(query: HogQLAutocomplete, team: Team) -> HogQLAutocompleteResponse:
    response = HogQLAutocompleteResponse(suggestions=[])

    database = create_hogql_database(team_id=team.pk, team_arg=team)

    for extra_characters in ["", MATCH_ANY_CHARACTER]:
        try:
            query.select = query.select[: query.endPosition] + extra_characters + query.select[query.endPosition :]
            query.endPosition = query.endPosition + len(extra_characters)

            select_ast = parse_select(query.select)
            if query.filters:
                select_ast = cast(ast.SelectQuery, replace_filters(select_ast, query.filters, team))

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
                table = get_table(database, nearest_select.select_from)
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

                    is_last_part = index >= (chain_len - 2)  # Ignore last chain part

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
