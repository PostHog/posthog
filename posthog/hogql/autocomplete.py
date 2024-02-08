from typing import List, Optional, cast
from posthog.hogql.database.database import Database, create_hogql_database
from posthog.hogql.database.models import LazyJoin, LazyTable, StringJSONDatabaseField, Table, VirtualTable
from posthog.hogql.filters import replace_filters
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


def extend_responses(keys: List[str], suggestions: List[AutocompleteCompletionItem]) -> None:
    suggestions.extend(
        [
            AutocompleteCompletionItem(
                insertText=key,
                label=key,
                kind=Kind.Field,
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

            if (
                isinstance(node, ast.Field)
                and isinstance(nearest_select, ast.SelectQuery)
                and nearest_select.select_from is not None
                and not isinstance(parent_node, ast.JoinExpr)
            ):
                table = get_table(database, nearest_select.select_from)
                if table is not None:
                    if len(node.chain) == 1:
                        fields = list(table.fields.keys())
                        extend_responses(fields, response.suggestions)
                    # TODO: we should do this recursively for deeper joins, e.g. properties.pdi.person.properties.$browser
                    # TODO: add logic for FieldTraverser field types
                    elif len(node.chain) == 2:
                        field = table.fields[str(node.chain[0])]
                        if isinstance(field, StringJSONDatabaseField):
                            if table.to_printed_hogql() == "events":
                                property_type = PropertyDefinition.Type.EVENT
                            elif table.to_printed_hogql() == "persons":
                                property_type = PropertyDefinition.Type.PERSON
                            elif table.to_printed_hogql() == "groups":
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
                            fields = list(table.fields.keys())
                            extend_responses(fields, response.suggestions)
                        elif isinstance(field, LazyJoin):
                            fields = list(field.join_table.fields.keys())
                            extend_responses(fields, response.suggestions)
        except Exception:
            pass

        if len(response.suggestions) != 0:
            break

    return response
